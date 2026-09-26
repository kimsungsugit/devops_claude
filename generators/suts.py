"""SUTS (Software Unit Test Specification) auto-generation engine.

Generates XLSM output from UDS function details and source code analysis.
Each unit function gets a dedicated TC with input/output variable columns
and multiple test sequences (boundary values, error conditions, etc.).
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from generators._artifact_check import apply_write_back_check
from generators._artifact_check import sheet_base_name as _sheet_base_name
from generators._xlsx_merge import merge_fresh
from generators.boundary_rows import BOUNDARY_PREFIX, find_boundaries
from generators.mcdc_design import build_mcdc_design, finalize_mcdc_design
from generators.safety_marks import resolve_safety_related as _resolve_safety_related
from generators.tc_profile import TC_PROFILE_EXTENDED, normalize_tc_profile
from generators.test_evidence import VERIFY_PREFIX, apply_sequence_evidence, summarize_expected_evidence
from generators.uds_unit_io import resolve_unit_io
from report_gen.c_return import returns_value
from report_gen.doc_kind import is_sds_filename
from report_gen.function_analyzer import split_param_annotations
from report_gen.requirements import (
    _asil_max_of,
    _extract_sds_partition_map,
    _load_component_map,
    _merge_sds_partition_map,
    component_verify_of,
    is_sds_placeholder_key,
    normalize_sds_key,
)
from report_gen.source_parser import is_const_type
from workflow.code_parser.c_parser import blank_c_comments, blank_dead_code

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ── 시트 레이아웃 — **납품 정본 기준** (KJPDS02_SwUTS v1.02, 189열) ──────────
#
# ⚠ 회사 표준 템플릿(v0.10)이 아니라 **정본**을 따른다. 실측(2026-08-11):
#   - 표준 템플릿 v0.10 = 28열. Input/Expected 가 `Param 1~10` 고정이고
#     Safety Related·Test Method 열이 **없다**. 실제 함수는 파라미터가 최대 96개라
#     템플릿 폭으로는 담기지 않는다.
#   - 정본 v1.02 = 189열. 프로젝트가 템플릿을 확장한 형태이고, 이것이 납품물이다.
#
# ⚠ 이전 판은 셋 중 **어느 것도 아닌 제3의 레이아웃**이었다(149열). `Description`
#   `Test Environment` `Precondition` `Sequence` 4열은 **STS 정본의 열**이라
#   SUTS 에 와 있으면 안 된다 — 열이 밀려 정본 파서가 전부 잘못 읽는다.
#
# 정본 실측 구조:
#   r3 밴드 : B3:G3 'Test Case' · H3:CZ3 'Input' · DA3:GF3 'Expected Result' · GG3 'Related ID'
#   r4 헤더 : B Index · C TC_ID · D Unit · E Safety Related · F Test Method
#             · G Test Case Generation Method · H ' '(시퀀스 번호) · I~ Inpt[n] · DA~ ExpR[n] · GG SUDS
#   r5~     : TC 블록 = 변수명 행 1개 + 시퀀스 행 N개 (B/C/D/E/GG 는 블록 전체 병합)
_BAND_ROW = 3
_HEADER_ROW = 4
_DATA_START_ROW = 5

_COL_INDEX = 2             # B   Index (연번 — 정본은 1..1014 연속)
_COL_TC_ID = 3             # C   TC_ID
_COL_UNIT = 4              # D   Unit (함수명)
_COL_SAFETY = 5            # E   Safety Related (O/X)
_COL_METHOD = 6            # F   Test Method (REQ/FI) — **시퀀스 그룹 단위**
_COL_GEN = 7               # G   Test Case Generation Method — 시퀀스 그룹 단위
_SEQ_COL = 8               # H   시퀀스 번호 (헤더는 공백 한 칸 — 정본 그대로)
_INPUT_COL_START = 9       # I   Inpt[0]
_INPUT_COL_END = 104       # CZ  Inpt[95]
_OUTPUT_COL_START = 105    # DA  ExpR[0]
_OUTPUT_COL_END = 188      # GF  ExpR[83]
_RELATED_COL = 189         # GG  SUDS

# 헤더 행(열 번호 → 라벨). `generate_suts_xlsm`이 시트에 쓰는 값이자, 영향도 탭의
# 문서 초안이 Excel 붙여넣기 TSV 열 순서를 얻는 **단일 출처**다(복제 금지).
_FIXED_HEADERS = {
    _COL_INDEX: "Index",
    _COL_TC_ID: "TC_ID",
    _COL_UNIT: "Unit",
    _COL_SAFETY: "Safety Related",
    _COL_METHOD: "Test Method",
    _COL_GEN: "Test Case Generation Method",
    _SEQ_COL: " ",
}
_RELATED_HEADER = "SUDS"   # Related ID 컬럼 라벨

# ── 값 어휘 — 정본과 Introduction(1.5/1.6)에서 온다 ─────────────────────────
#
# ⚠ 이전 판은 `FIT`/`FNCT`/`RVW` 를 썼다. 그건 **STS 어휘**이고 SwUTS Introduction
#   1.5 표에 아예 없는 값이다. 정본 실측: REQ 1,437 · FI 815 (그 둘뿐).
_METHOD_REQ = "REQ"        # Requirements based test — 유효 범위 시험
_METHOD_FI = "FI"          # Fault Injection Test — 유효 범위 밖 시험
# 유효 범위를 벗어나는 값을 넣는 전략 = 고장 주입. 정본도 경계 초과 시퀀스를 FI 로 묶는다
# (첫 TC: seq 1~3 REQ / 4~7 FI).
_FI_STRATEGIES = frozenset({"BV_MIN_INV", "BV_MAX_INV", "ERROR_PATH"})

# ⚠ 결합자는 **문서마다 다르다**. SwUTS 정본은 슬래시(`AOR/ABV`), SwITS 정본은
#   쉼표(`AOR, AEC`). 통일하지 말 것 — 각 정본을 따른다.
#   정본 실측: AOR/ABV 1,638 · AOR/AEC 636 (그 둘뿐).
_GEN_BOUNDARY = "AOR/ABV"  # 경계값 분석
_GEN_EQUIV = "AOR/AEC"     # 등가 분할(조건·분기 조합)

_MAX_SEQUENCES = 10
# 전략 카탈로그의 **이론적 최대는 30** 이다(실측, `generate_sequences` 의 append 지점):
#   6 BV + 4 COND_COMB + 6 SWITCH + 3 LOOP + 3 GLOBAL + 1 VOID + 7 MC/DC(설계 벡터 7)
#   (R80) MC/DC 는 예전 `BASE 1 + 토글 6` 을 **설계 벡터 7개**로 바꿨다 — 같은 자리 수(정본 규모 유지), 내용만 식 평가로
#   찾은 독립 영향 쌍의 입력이다. 조건 n 개의 unique-cause 는 대개 n+1 벡터라 7 이면 조건 6개까지 다 담긴다.
#
# ⚠ 그러므로 24 는 "카탈로그 전체" 가 아니라 **캡**이다. 예전 주석은 `6 MC/DC` 로 적어
#   `MCDC_BASE` 를 빠뜨렸고 합도 29 였다 — 그 숫자가 화면 공시문까지 번져 사용자에게
#   "24종 중 이 수만큼" 이라고 잘못 말했다.
# ⚠ MC/DC 는 `strategies` 의 **맨 끝**(GAP 6)이고 `_cap`(:2043 `strategies[:max_seq]`)이
#   앞에서 자르므로, **switch-case 가 있는 함수는 기본값 24 에서도 MC/DC 가 빠진다**
#   (switch 6개면 MC/DC 7 → 1). ISO 26262 ASIL D 는 MC/DC 가 필수다.
_DEFAULT_SEQ_COUNT = 24
_STRATEGY_CATALOG_MAX = 30
# 기본 카탈로그가 전략 종류별로 내는 **자리 수**. 생성부(`generate_sequences`)와 판별부(`is_extended_strategy`)가
# 같은 상수를 본다 — 따로 적으면 한쪽만 바뀌어도 아무것도 안 깨진 채 공시가 틀린다(R75 리뷰 X5).
_BASE_SWITCH_SLOTS = 6
_BASE_GLOBAL_SLOTS = 3
_BASE_MCDC_SLOTS = 7

# 시험 범위의 **유일한 정의**. 준비 게이트(`docgen_preflight`)도 이걸 import 한다.
SCOPE_REFERENCE = "suds"    # SwUDS 설계 ID 가 있는 함수만 — 정본과 같은 범위(기본)
SCOPE_SOURCE = "source"     # 소스에서 찾은 함수 전부 — SwUDS 미대조
SCOPES = (SCOPE_REFERENCE, SCOPE_SOURCE)


def normalize_scope(scope: Any) -> "tuple[str, str]":
    """``(정규화된 범위, 알 수 없었던 원본 or "")``.

    ⚠ 예전엔 `if _scope == "suds": … else: 소스 전체` 였다. 그래서 `suds` 가 **아닌
    모든 값**(오타·옛 저장값·미래의 세 번째 범위)이 조용히 **가장 넓은 범위**로 떨어져,
    정본에 없는 함수가 ISO 26262 산출물에 들어갔다. 게다가 준비 게이트는 반대로
    `== "source"` 로 판정해서 같은 값에 **"정본 기준"** 이라고 안심시켰다 —
    한 값에 두 화면이 반대말을 했다.

    모르는 값은 **문서화된 기본값**(`suds`, 좁은 쪽)으로 떨어지고, 그 사실을 함께 돌려준다.
    """
    raw = str(scope or "").strip()
    low = raw.lower()
    if not low:
        return SCOPE_REFERENCE, ""
    if low in SCOPES:
        return low, ""
    return SCOPE_REFERENCE, raw


def apply_scope(units: List[Dict[str, Any]],
                scope: Any) -> "tuple[List[Dict[str, Any]], List[str]]":
    """시험 범위를 적용해 ``(남길 unit, 보고할 문장들)`` 을 돌려준다.

    SUTS 는 SwUDS(단위 설계서)를 근거로 만드는 문서이고 정본도 그 범위다 — 정본 1,005
    함수는 SwUDS 설계 ID 1,026 과 교집합 1,001 로 사실상 일치한다(실측 2026-08-11).
    소스에는 그보다 많은 함수가 있고(실측 1,160), 그중 155개는 정본이 시험 대상으로
    삼지 않는다(부트로더 계열 등).

    ⚠ 이건 걷어낸 `docs/uds_function_swcom_override.json` 필터와 **성질이 다르다**.
      그건 저장소에 박힌 251개 목록이라 프로젝트가 바뀌어도 같은 걸로 잘랐다. 이건
      **그 프로젝트의 SwUDS 문서**가 근거이고, 문서가 없으면 필터도 걸지 않는다.

    ⚠ 범위를 좁힌 사실은 **반드시 보고한다** — 조용히 자르면 커버리지가 또 자기 자신을
      분모로 삼는다. 그래서 판정과 보고를 한 함수에 묶어 둔다(호출부가 문장만 버리는
      일을 막는다).

    ⚠ 본체에 인라인으로 두면 시험할 수가 없어, 가장 무거운 판정(어떤 함수가 ISO 26262
      산출물에 들어가는가)이 **전체 생성 없이는 검증 불가**였다. 그래서 뽑아 둔다.
    """
    notes: List[str] = []
    _scope, _bad = normalize_scope(scope)
    if _bad:
        # 알 수 없는 값을 조용히 넘기지 않는다. 예전엔 `suds` 가 아닌 **모든** 값이
        # `else` 로 흘러 **가장 넓은 범위**(SwUDS 미대조)가 됐다 — 정본에 없는 함수가
        # ISO 26262 산출물에 들어가는데 아무 데도 안 남았다.
        msg = f"알 수 없는 시험 범위 `{_bad}` — 기본값 `suds`(정본 기준)로 진행합니다."
        _logger.warning("SUTS scope: %s", msg)
        notes.append(msg)
    if _scope == SCOPE_REFERENCE:
        with_id = [u for u in units if str(u.get("suds_id") or "").strip()]
        if not with_id:
            msg = ("SwUDS 설계 ID 를 하나도 확보하지 못해 범위를 좁히지 않았습니다 "
                   "(SwUDS 문서가 없거나 읽지 못했습니다).")
            _logger.warning("SUTS scope=suds: %s", msg)
            notes.append(msg)
        elif len(with_id) < len(units):
            msg = (f"SwUDS 기반 범위: 소스 {len(units)}개 중 설계 ID 가 있는 "
                   f"{len(with_id)}개만 시험합니다 "
                   f"({len(units) - len(with_id)}개 제외 — SwUDS 에 없는 함수).")
            _logger.info("SUTS scope=suds: %s", msg)
            notes.append(msg)
            units = with_id
    else:
        msg = f"소스 전체 범위: {len(units)}개 함수 전부를 시험합니다(SwUDS 미대조)."
        _logger.info("SUTS scope=source: %s", msg)
        notes.append(msg)
    return units, notes


_GEN_METHODS = {"AEC, ABV", "ABV, AOR", "AOR", "ABV"}
_DEFAULT_GEN_METHOD = "AEC, ABV"
_DEFAULT_TEST_ENV = "SwTE_01"

_SDS_MAP_CACHE: Optional[Dict[str, Dict[str, str]]] = None

# (R52 N39) `_merge_sds_partition_map` 은 `report_gen.requirements` 단일 출처 — UDS 세 경로와 같은 first-wins 규칙.


def load_sds_map_from(sds_docx_path: str) -> Dict[str, Dict[str, str]]:
    """사용자가 지정한 SDS 문서 하나에서 파티션 맵(ASIL/related/description)을 읽는다.

    `_load_default_sds_map`(저장소 `docs/` 글롭)과 달리 **경로를 그대로 존중**한다.
    SUTS 생성기는 오래도록 `sds_docx_path` 인자를 받고도 본문에서 쓰지 않아,
    프로젝트가 무엇이든 저장소 `docs/`에 들어있는 SDS(현재 HDPDM01)로 ASIL을 채웠다
    — 다른 프로젝트의 안전 등급이 조용히 섞이는 경로였다.
    """
    if not sds_docx_path:
        return {}
    merged: Dict[str, Dict[str, str]] = {}
    try:
        _merge_sds_partition_map(merged, _extract_sds_partition_map(sds_docx_path))
    except Exception as exc:
        _logger.warning("SDS 파티션 맵 파싱 실패 — ASIL 보강 생략: %s (%s)", sds_docx_path, exc)
        return {}
    return merged


def _resolve_sds_map(sds_docx_path: Optional[str]) -> Optional[Dict[str, Dict[str, str]]]:
    """SUTS ASIL 보강에 쓸 SDS 맵을 확보한다. None이면 호출자가 폴백을 쓴다.

    입력은 resolver 경유(`_resolved_doc_input`)라 cloudium worker-only 경로도 잡는다.
    지정했는데 못 쓰게 된 경우는 **반드시 경고를 남긴다** — 폴백(저장소 `docs/` 글롭)이
    조용히 대신하면, 다른 프로젝트의 ASIL로 채워진 산출물을 정상으로 오인한다.
    """
    if not sds_docx_path:
        return None
    with _resolved_doc_input(sds_docx_path, "SDS") as local:
        if not local:
            _logger.warning(
                "SUTS: SDS 입력을 확보하지 못해 ASIL 보강이 저장소 docs/ 폴백(프로젝트 무관)으로 "
                "넘어간다: %s", sds_docx_path)
            return None
        sds_map = load_sds_map_from(local)
    if not sds_map:
        _logger.warning(
            "SUTS: SDS를 지정했으나 파티션 0건 — ASIL 보강이 저장소 docs/ 폴백(프로젝트 무관)으로 "
            "넘어간다: %s", sds_docx_path)
        return None
    _logger.info("SUTS: SDS 파티션 %d건 로드 — ASIL 출처=%s", len(sds_map), sds_docx_path)
    return sds_map


def _load_default_sds_map() -> Dict[str, Dict[str, str]]:
    """저장소 `docs/`의 SDS 글롭 폴백.

    ⚠ 프로젝트 무관이다 — 호출자가 SDS 경로를 알고 있으면 `load_sds_map_from`을 쓸 것.
    """
    global _SDS_MAP_CACHE
    if _SDS_MAP_CACHE is not None:
        return _SDS_MAP_CACHE
    docs_dir = Path(__file__).resolve().parents[1] / "docs"
    merged: Dict[str, Dict[str, str]] = {}
    picked: List[str] = []
    if docs_dir.exists():
        for path in docs_dir.glob("*.docx"):
            # `"sds" in name` 은 `SwDS` 표기를 놓친다("swds" 에 "sds" 없음) — 단일 출처 사용.
            if not is_sds_filename(path.name):
                continue
            picked.append(path.name)
            _merge_sds_partition_map(merged, _extract_sds_partition_map(str(path)))
    if merged:
        # ⚠ 침묵 금지 — 이 맵으로 단위 ASIL 을 채우는데 출처가 **다른 프로젝트**일 수 있다.
        _logger.warning(
            "SDS 미지정 — 저장소 docs/ 글롭 폴백 사용(**프로젝트 무관**): %s (%d 엔트리). "
            "대상 프로젝트의 SDS 를 `load_sds_map_from` 으로 넘기면 이 폴백은 쓰이지 않는다",
            ", ".join(picked) or "(없음)", len(merged))
    _SDS_MAP_CACHE = merged
    return merged


def _resolve_unit_asil(info: Dict[str, Any],
                       sds_map: Dict[str, Dict[str, str]]) -> Tuple[str, str]:
    """모듈명으로 SDS 파티션의 ASIL 을 찾는다 → `(등급, 근거)`.

    근거는 `"sds-exact"` · `"sds-fuzzy"` · `"sds-fuzzy-conflict"` · `""`(못 찾음).

    ## ⚠ 값은 일부러 그대로 둔다 — 대안 6개를 다 재봤고 **하나도 이기지 못했다**

    2단계 사슬이다: ①후보(모듈명·`_pds` 제거·토큰화)로 **정확 키** 조회(등급 있는 것만)
    → ②정규화 후 **부분문자열 양방향** 매칭의 **첫 일치**를 그대로 채택(그 파티션에
    등급이 없어도 거기서 멈춘다).

    ②는 누가 봐도 허술하다. 실측(2026-08-14, KJPDS02_PV · SwUDS 를 끈 상태 =
    UDS 없는 프로젝트 시뮬 · 정본이 `Safety Related` 를 채운 868칸):

        정책                      일치            over  under  빈칸
        **현행**                 689  79.4%       88     2     89
        빈 등급 스킵+첫 매치        689  79.4%      108     2     69
        빈 등급 스킵+가장 구체적     689  79.4%      108     2     69
        후보들이 합의해야 채택       563  64.9%       18     2    285
        max 등급                 621  71.5%      176     2     69
        정확 키만(퍼지 폐지)        400  46.1%       17     2    449
        파일→SwCom→SDS 정확조회    672  77.4%       89   **46**   61

    · "등급 없는 파티션에서 멈추는 건 버그" 라고 고쳐보면 **더 나빠진다**. 실제로
      멈추게 만든 첫 매치가 `(swdsg) software architecture design guideline…docx`
      (문서 목록 행 — `Lin` 이 `guide**lin**e` 에 걸렸다)인데, 그 뒤에 있던 등급을
      채워 넣으면 정본이 `X` 라 한 20칸이 전부 `O` 가 된다(over 88 → 108).
    · `docs/component_map.json`(파일→`SwCom_NN`) 경유 정확 조회는 **under 를 2 → 46**
      으로 키운다. under-classification 은 ISO 26262 에서 가장 위험한 방향이다.

    그래서 **값은 안 건드리고 근거만 돌려준다.** 라이브에서는 어차피 SwUDS 표가
    먼저 결정하므로(그쪽 방향 오류 0) 이 사슬은 UDS 가 침묵한 unit 에만 쓰인다.

    ⚠ 다만 침묵하지는 않는다: 퍼지 매치의 후보 등급이 **갈리는데도** 하나를 집는
      경우가 실측 380건 중 **216건(57%)** 이다. 그건 사전 순서가 안전 등급을 정했다는
      뜻이라, `sds-fuzzy-conflict` 로 표시하고 호출부가 센다.

    ## 정규화는 `report_gen.requirements.normalize_sds_key` **단일 출처**를 쓴다

    예전엔 여기와 `sts.py::_lookup_sds_related_ids` 가 각자 `[^a-z0-9]` 를 복제하고
    있었고, 그건 한글을 통째로 버려 `차속에 따른 도어 open 방지` 를 `open` 으로
    쪼그라뜨린다. STS 쪽에서는 그 유령 키가 **틀린 요구 링크**를 만들었다.
    여기서는 실측상 **값이 안 바뀐다**(868칸 · 일치 689 · over 88 · under 2 — 한글
    보존/placeholder 배제 4개 조합이 전부 동일). 그래도 같이 옮긴다 — 복제를 남겨
    두면 다음에 또 한쪽만 고쳐진다.
    """
    _norm = normalize_sds_key

    module_name = str(info.get("module_name") or "").strip()
    candidates: List[str] = []
    if module_name:
        candidates.append(module_name)
        base = re.sub(r"_pds$", "", module_name, flags=re.I)
        candidates.append(base)
        tokenized = re.sub(r"([a-z])([A-Z])", r"\1 \2", base.replace("_", " "))
        tokenized = re.sub(r"\bctrl\b", "control", tokenized, flags=re.I)
        tokenized = re.sub(r"\bdiag\b", "diagnostic", tokenized, flags=re.I)
        words = [w for w in tokenized.split() if w.lower() not in {"ap", "drv", "sys", "pds", "main", "func"}]
        if words:
            candidates.append(" ".join(words))
    for candidate in candidates:
        direct = sds_map.get(candidate.lower())
        if direct and direct.get("asil"):
            return str(direct["asil"]).strip(), "sds-exact"
    # ⚠ **한 번만 훑는다.** 채택값(= 첫 매치, 현행 그대로)과 "후보 등급이 갈리는가"를
    #   같은 순회에서 얻는다. 근거를 재려고 두 번 돌면 같은 순회 규칙을 두 벌 들게 되고,
    #   그러면 다음에 한쪽만 고쳐진다(이 저장소가 여러 번 겪은 모양).
    picked: Optional[str] = None
    grades: set[str] = set()
    for candidate in candidates:
        nc = _norm(candidate)
        if not nc:
            continue
        for key, value in sds_map.items():
            nk = _norm(key)
            if not nk or is_sds_placeholder_key(nk):
                continue
            # ⚠ (R76 N106) STS 요구 매핑은 토큰 경계 규칙(`contains_at_token_start`)으로 갔지만 **여기는 일부러 그대로**다 —
            #   `test_empty_grade_first_match_still_stops_the_pick` 이 묶는 결정(고치면 정본 대비 over 88→108).
            if nc == nk or nc in nk or nk in nc:
                got = str(value.get("asil") or "").strip()
                if picked is None:
                    picked = got          # 현행 채택 규칙: 첫 매치(빈 등급이어도 여기서 끝)
                if got:
                    grades.add(got.upper())
            # 채택값과 "갈린다"가 둘 다 확정되면 더 봐도 결론이 안 바뀐다.
            # (옛 판은 첫 매치에서 곧장 return 했으므로, 여기서 안 끊으면 파티션 871개를
            #  함수마다 끝까지 훑는 순수 손해가 된다.)
            if picked is not None and len(grades) > 1:
                break
        if picked is not None and len(grades) > 1:
            break
    if picked is None:
        return "", ""
    return picked, ("sds-fuzzy-conflict" if len(grades) > 1 else "sds-fuzzy")

_SRS_REQ_ID_PAT = re.compile(
    r"\b(?:SW[_R]?|SRS|Sw|HDPDM\d*|SWR|SWS|SYSRS)[_-]?\d[\w_-]*",
    re.I,
)


def _resolve_srs_req_ids_for_function(
    func_name: str,
    sds_map: Dict[str, Dict[str, str]],
) -> str:
    """Resolve SRS requirement IDs for a function via SDS partition map `related` field."""
    if not sds_map or not func_name:
        return ""
    candidates = [func_name.lower(), func_name.lower().replace("_", " ")]
    for candidate in candidates:
        entry = sds_map.get(candidate)
        if entry:
            related = str(entry.get("related", "") or "")
            ids = _SRS_REQ_ID_PAT.findall(related)
            if ids:
                return ", ".join(dict.fromkeys(ids))
    # Fuzzy: partial name match
    fn_lower = func_name.lower()
    for key, entry in sds_map.items():
        if fn_lower in key or key in fn_lower:
            related = str(entry.get("related", "") or "")
            ids = _SRS_REQ_ID_PAT.findall(related)
            if ids:
                return ", ".join(dict.fromkeys(ids))
    return ""


# C type boundary values (min_invalid, min_valid, zero, mid, max_valid, max_invalid)
_TYPE_BOUNDARIES: Dict[str, Dict[str, Any]] = {
    "uint8_t":  {"min_inv": -1,     "min": 0,      "mid": 127,   "max": 255,     "max_inv": 256},
    "uint8":    {"min_inv": -1,     "min": 0,      "mid": 127,   "max": 255,     "max_inv": 256},
    "uint16_t": {"min_inv": -1,     "min": 0,      "mid": 32767, "max": 65535,   "max_inv": 65536},
    "uint16":   {"min_inv": -1,     "min": 0,      "mid": 32767, "max": 65535,   "max_inv": 65536},
    # ⚠ mid 는 **부호 없는 폭의 중앙**이다: uint8=2**7-1(127) · uint16=2**15-1(32767).
    #   uint32 만 `2**15`(32768) 로 적혀 있었다 — 2**15-1 도 2**31-1 도 아닌 값이라
    #   오타로 보이고, 실측이 그걸 뒷받침한다: 정본 SUTS(KJPDS02_PV)에서 **32768 은
    #   uint32 칸에 0회** 등장하고 정본은 같은 자리에 `0x7FFFFFFF`(2**31-1)를 쓴다.
    #   그 값을 우리가 못 내던 칸이 52개였다(R25 실측).
    "uint32_t": {"min_inv": -1,     "min": 0,      "mid": 2**31-1, "max": 2**32-1, "max_inv": 2**32},
    "int8_t":   {"min_inv": -129,   "min": -128,   "mid": 0,     "max": 127,     "max_inv": 128},
    "int16_t":  {"min_inv": -32769, "min": -32768, "mid": 0,     "max": 32767,   "max_inv": 32768},
    "int16":    {"min_inv": -32769, "min": -32768, "mid": 0,     "max": 32767,   "max_inv": 32768},
    "int32_t":  {"min_inv": -(2**31)-1, "min": -(2**31), "mid": 0, "max": 2**31-1, "max_inv": 2**31},
    "float":    {"min_inv": -1001.0, "min": -1000.0, "mid": 0.0,  "max": 1000.0,  "max_inv": 1001.0},
    "bool":     {"min_inv": -1,     "min": 0,       "mid": 0,    "max": 1,       "max_inv": 2},
    "bit":      {"min_inv": -1,     "min": 0,       "mid": 0,    "max": 1,       "max_inv": 2},
}
_DEFAULT_BOUNDARY = {"min_inv": -1, "min": 0, "mid": 127, "max": 255, "max_inv": 256}

#: 범위 밖 입력의 기대값을 모를 때 값 앞에 붙는 표시 — 쓰는 곳(기대값)과 세는 곳(품질 리포트)이 같은 상수를 본다.
_VERIFY_NEEDED_PREFIX = "[검증 필요]"

# Known C types where out-of-range input defaults to saturation (no "[검증 필요]")
# Unsigned types: deterministic wrap/saturation.
# Fixed-width signed (int8/16/32): 임베디드 환경에서 포화 처리 일반적 (컴파일러 -fwrapv 또는 HW saturation).
# C 표준 signed (char, short, long, int): overflow = UB → "[검증 필요]" 유지.
_KNOWN_SATURATE_TYPES = frozenset({
    "uint8", "uint16", "uint32", "int8", "int16", "int32",
    "float", "bit", "bool", "byte", "word", "dword",
    "unsignedchar", "unsignedshort", "unsignedlong", "unsignedint",
})

# Strategy labels for boundary-value test sequences (module-level constant)
_STRAT_LABEL: Dict[str, str] = {
    "BV_MIN_INV": "유효 하한 초과 (경계-1): 에러/포화 처리 확인",
    "BV_MIN":     "최솟값 경계 입력: 최솟값에서 정상 처리 확인",
    "BV_MID":     "정상 중간값 입력: 정상 동작 범위 확인",
    "BV_MAX":     "최댓값 경계 입력: 최댓값에서 정상 처리 확인",
    "BV_MAX_INV": "유효 상한 초과 (경계+1): 에러/포화 처리 확인",
    "MIXED":      "혼합 경계값: 짝수 인수=최솟값, 홀수 인수=최댓값 조합",
}

def _get_strategy_label(strat_name: str, input_vars: Optional[List[str]] = None,
                        switch_cases: Optional[List[Tuple[str, Any, str]]] = None,
                        loop_var: str = "",
                        global_vars: Optional[List[str]] = None) -> str:
    """Get human-readable label for any strategy including COND_COMB, SWITCH, LOOP, GLOBAL."""
    input_vars = input_vars or []
    switch_cases = switch_cases or []
    global_vars = global_vars or []
    if strat_name in _STRAT_LABEL:
        return _STRAT_LABEL[strat_name]
    if strat_name.startswith("COND_COMB_"):
        idx = int(strat_name.split("_")[-1])
        var = input_vars[idx] if idx < len(input_vars) else f"var{idx}"
        # (R75) 값은 짝수 번째=최솟값·홀수 번째=최댓값인데 라벨은 늘 "최솟값" 이라 표의 값과 설명이 어긋났다.
        side = "최솟값" if idx % 2 == 0 else "최댓값"
        return f"조건 조합: {var}={side}, 나머지=중간값 → 분기 커버리지 향상"
    if strat_name.startswith("OAT_"):
        _, _i, _side = strat_name.split("_")
        idx = int(_i)
        var = input_vars[idx] if idx < len(input_vars) else f"var{idx}"
        return f"단독 경계: {var}={'최솟값' if _side == 'MIN' else '최댓값'}, 나머지=중간값 → 입력별 경계 영향 분리"
    if strat_name.startswith("SWITCH_"):
        idx = int(strat_name.split("_")[-1])
        if idx < len(switch_cases):
            sw_var, sw_val, sw_label = switch_cases[idx]
            return f"Switch-case: {sw_var}={sw_val} ({sw_label}) → case 분기 커버"
        return f"Switch-case: case {idx}"
    if strat_name == "LOOP_ZERO":
        return f"루프 경계: {loop_var or 'counter'}=0 → 루프 미실행 경로 확인"
    if strat_name == "LOOP_ONE":
        return f"루프 경계: {loop_var or 'counter'}=1 → 루프 1회 실행 경로"
    if strat_name == "LOOP_MAX":
        return f"루프 경계: {loop_var or 'counter'}=최댓값 → 루프 최대 반복 경로"
    if strat_name.startswith("GLOBAL_"):
        idx = int(strat_name.split("_")[-1])
        gv = global_vars[idx] if idx < len(global_vars) else f"global{idx}"
        return f"글로벌 상태: {gv}=최솟값 → 글로벌 의존 분기 커버"
    if strat_name == "VOID_SIDE_EFFECT":
        return "Void 부작용: 입력 경계 초과 → 글로벌 변수 상태 변화 검증"
    if strat_name.startswith("MCDC_"):
        # 실제 라벨은 생성부가 쌍 구성(결정·조건·진리값)으로 덮어쓴다(`_mcdc_vector_label`). 여기는 이름만 온 경우의 자리표시다.
        return "MC/DC 설계 벡터 (식 평가, 도달성 미검증·미실행)"
    return strat_name

# Domain-keyword based float boundaries for physical/engineering signals
_FLOAT_DOMAIN_BOUNDS: List[Tuple[List[str], Dict[str, Any]]] = [
    (["voltage", "volt", "_v_", "_vbat", "_vcc"],
     {"min_inv": -1.0, "min": 0.0, "mid": 12.0, "max": 60.0, "max_inv": 61.0}),
    (["temperature", "temp", "_temp", "_t_"],
     {"min_inv": -41.0, "min": -40.0, "mid": 25.0, "max": 150.0, "max_inv": 151.0}),
    (["speed", "_spd", "velocity", "_vel"],
     {"min_inv": -1.0, "min": 0.0, "mid": 60.0, "max": 300.0, "max_inv": 301.0}),
    (["pressure", "_pres", "_press"],
     {"min_inv": -0.1, "min": 0.0, "mid": 2.5, "max": 10.0, "max_inv": 10.1}),
    (["current", "_cur", "_amp"],
     {"min_inv": -0.1, "min": 0.0, "mid": 5.0, "max": 50.0, "max_inv": 51.0}),
    (["angle", "_ang", "degree", "_deg"],
     {"min_inv": -1.0, "min": 0.0, "mid": 90.0, "max": 360.0, "max_inv": 361.0}),
    (["percent", "_pct", "ratio", "_ratio"],
     {"min_inv": -1.0, "min": 0.0, "mid": 50.0, "max": 100.0, "max_inv": 101.0}),
]


def _get_float_bounds_for_var(var_name: str) -> Dict[str, Any]:
    """Return domain-specific float boundaries based on variable name keywords."""
    name_lower = var_name.lower()
    for keywords, bounds in _FLOAT_DOMAIN_BOUNDS:
        if any(kw in name_lower for kw in keywords):
            return bounds
    return _TYPE_BOUNDARIES["float"]


# Patterns for inferring types from variable names
_TYPE_NAME_PATTERNS = [
    (re.compile(r"\bu8[gs]?_|uint8|U8|BYTE", re.I), "uint8_t"),
    (re.compile(r"\bu16[gs]?_|uint16|U16|WORD", re.I), "uint16_t"),
    (re.compile(r"\bu32[gs]?_|uint32|U32|DWORD", re.I), "uint32_t"),
    (re.compile(r"\bs8[gs]?_|int8[^_]|S8", re.I), "int8_t"),
    (re.compile(r"\bs16[gs]?_|int16|S16", re.I), "int16_t"),
    (re.compile(r"\bs32[gs]?_|int32|S32", re.I), "int32_t"),
    (re.compile(r"\bBits\.|_F\b|_Flag|_Sta\b|_Enable|_Disable", re.I), "bit"),
    (re.compile(r"\bf32|float|FLOAT", re.I), "float"),
    (re.compile(r"\bbool\b|BOOL|boolean", re.I), "bool"),
]


# ---------------------------------------------------------------------------
# Phase 1: Data extraction
# ---------------------------------------------------------------------------

_TYPE_NAMES = {
    "U8", "U16", "U32", "S8", "S16", "S32",
    "uint8_t", "uint16_t", "uint32_t", "int8_t", "int16_t", "int32_t",
    "BOOL", "void", "char", "int", "float", "double", "long",
    "unsigned", "signed", "short", "const", "volatile", "static",
    # LIN 스택·Processor Expert 타입. 반환값 슬롯 교정이 주 경로지만, 참조 SUDS
    # 문서 경유분처럼 태그 없이 들어오는 입구를 위해 안전망으로 둔다.
    "U64", "S64", "l_u8", "l_u16", "l_u32", "l_bool", "byte", "word", "bool", "dword",
}

# Local temp variable prefixes — these live on stack, not meaningful for unit test I/O
_LOCAL_TEMP_PATS = re.compile(
    r"^(u8t_|u16t_|u32t_|s8t_|s16t_|s32t_|sf_t|tmpVal|temp_|tmp_|loop_|idx_|cnt_|i$|j$|k$|n$)",
    re.I,
)

# Prefixes that are clearly global reads (function inputs)
_INPUT_PREFIXES = ("u8g_", "u16g_", "u32g_", "s16g_", "s8g_", "s32g_")
# Prefixes that are clearly module-static writes (function outputs)
_OUTPUT_PREFIXES = ("u8s_", "u16s_", "u32s_", "s16s_", "s32s_")
# Hardware registers — typically both read and written
_REG_PAT = re.compile(r"^REG_|^lin_|^PS\.|^DiagData\.")

# 파서가 붙이는 방향 태그. **앵커 매칭이어야 한다** — 예전엔 `"[IN]" in tag` 였는데
# `"[IN]" in "[INOUT] x"` 도 `"[OUT]" in "[INOUT] x"` 도 **둘 다 False** 다(`[INOUT]` 안에
# `[IN]`·`[OUT]` 이 연속으로 들어있지 않다). 그래서 파서가 가장 정확하게 아는 축인
# `[INOUT]` 이 통째로 "태그 없음"으로 떨어져 아래 프리픽스 휴리스틱을 타고, 대부분
# `elif not is_in_global: role_out = True` 에 걸려 **출력 전용**이 됐다.
# 실측(KJPDS02 파서 산출 750함수 중 전역 보유 556개): [IN] 1,423 · [OUT] 1,052 ·
# **[INOUT] 305** · [INDIRECT] 1,114 · 무태그 529. `LinSend` 는 `[INOUT] s_LinFrame …` 를
# 받고도 입력이 0개였고 같은 이름이 기대결과에만 실렸다(정본은 입력에 둔다).
#
# ⚠ **`INDIRECT2` 를 빼먹으면 안 된다** — 같은 함정이 한 번 더 있었다. 2홉 전파는
#   `[INDIRECT2]` 로 태그되는데(`report_gen/uds_generator.py:2107`), 이 정규식이
#   `INDIRECT` 만 알면 `[INDIRECT2]` 는 매칭에 실패해 **"태그 없음"** 으로 떨어지고
#   아래 프리픽스 휴리스틱을 탄다. 그 결과 **1홉(`[INDIRECT]`)은 입력에서 빼는데
#   2홉은 입력으로 올리는**, 증거가 멀수록 느슨해지는 뒤집힌 판정이 됐다.
#   실측(2026-08-12, KJPDS02): SPI 레지스터가 살아나자 `g_DrvIn_DRV8706SQ_Init` ·
#   `..._Left` · `s_IIM20670_Init` 3건이 정본엔 입력 0개인데 `_SPI0SR` 계열을
#   입력으로 냈다 — 읽기는 2홉 아래 `u16g_DrvIn_SPI_DataTransfer` 안에서 일어난다.
_DIR_TAG_PAT = re.compile(r"^\s*\[(IN|OUT|INOUT|INDIRECT2|INDIRECT)\]", re.I)

# 태그를 안 붙이는 생산자(참조 SUDS 문서 경유 등)의 키워드 표기. **선두 토큰만** 본다 —
# 엔트리 전체를 substring 매칭하면 변수 **이름 안의 글자**가 방향을 정한다(`…READY` 의
# `READ`). 자세한 실측은 아래 `collect_unit_functions` 의 폴백 주석 참조.
_KEYWORD_DIR_PAT = re.compile(r"^\s*(READ|WRITE|RHS|LHS)\b", re.I)


def dir_tag(entry: Any) -> str:
    """전역 엔트리의 방향 태그(대문자). 태그가 없으면 빈 문자열.

    **방향 태그 판정의 단일 출처.** 소비처가 각자 정규식을 들고 있으면 태그가
    하나 늘 때 한쪽만 고쳐진다 — 이 저장소가 `[INOUT]`(A-1)과 `[INDIRECT2]`
    두 번 겪은 실패다.
    """
    m = _DIR_TAG_PAT.match(str(entry or ""))
    return m.group(1).upper() if m else ""


def _is_const_global(name: str, gim: Optional[Dict[str, Dict[str, str]]]) -> bool:
    """`const` 전역은 시험 입력으로 **설정할 수 없고** 기대결과로 **변하지도 않는다**.

    실측(KJPDS02_PV 정본 1,005 unit): 정본 SUTS 는 const 전역을 입력 **0칸** · 기대
    **0칸** — 어느 입도로도 단 한 번도 적지 않는다. 우리는 419칸(입력 160 · 기대 259)
    을 냈고 그중 정본과 일치한 건 **0** 이다. 즉 억제의 대가가 0 이다.
    `au32_Sha256RoundConstants[0..63]` 처럼 배열이면 원소 확장이 노이즈를 배로 불린다.

    ⚠ 파라미터의 `const`(`const U8 *p`)는 **대상이 아니다** — 가리키는 곳이 읽기
      전용일 뿐 그 버퍼는 시험이 채워 넣어야 하는 입력이다. 이 판정은 전역 루프에서만
      쓴다.
    ⚠ `gim` 이 비면 판정할 근거가 없어 **억제하지 않는다**. 호출부가 안 넘기면 산출물이
      달라지므로, 아래 요약 로그가 그 사실을 명시한다(조용한 분기 금지).
    """
    return is_const_type(((gim or {}).get(name) or {}).get("type"))


def collect_unit_functions(
    function_details: Dict[str, Dict[str, Any]],
    globals_info_map: Optional[Dict[str, Dict[str, str]]] = None,
    sds_map: Optional[Dict[str, Dict[str, str]]] = None,
    uds_io_map: Optional[Dict[str, Any]] = None,
    struct_members: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Collect and structure unit functions from report_generator output.

    Matching reference SUTS patterns: variables can appear as BOTH input and
    output (read-modify-write). Local temps are excluded. REG_ and state
    vars are placed in output. Caps at reasonable counts per function.

    Args:
        sds_map: ASIL/related 보강에 쓸 SDS 파티션 맵. None이면 저장소 `docs/` 글롭
            폴백(`_load_default_sds_map`)을 쓴다 — **프로젝트 무관**이므로 호출자가
            대상 프로젝트의 SDS를 알고 있으면 `load_sds_map_from`으로 만들어 넘길 것.
    """
    gim = globals_info_map or {}
    # 시험 범위 판정용. 실패해도 산출물은 그대로 나가야 하므로 빈 맵으로 떨어진다
    # (판정 불가와 '면제 아님'을 섞지 않도록 아래 요약이 맵 부재를 명시한다).
    try:
        _cmap = _load_component_map()
    except Exception as _cm_exc:  # noqa: BLE001 — 보고용 부가 정보다
        _logger.warning("component_map 로드 실패 — 시험 범위 보고 생략: %s", _cm_exc)
        _cmap = {}
    # 구조체 **배열** 전역(`SlipDetectPhase_t g_SlipDetectPhases[4]`)의 첨자는 root 에
    # 붙는다. unit 마다 안 바뀌므로 루프 **밖에서** 한 번만 만든다.
    _root_sizes: Dict[str, Tuple[int, ...]] = {}
    for _rn, _ri in gim.items():
        _rd = _decl_dims_from_array_field(str((_ri or {}).get("array") or ""))
        if _rd and _dim_product(_rd) > 1:
            _root_sizes[str(_rn)] = _rd
    # 전역 선언 타입도 unit 마다 안 바뀐다. 안에서 만들면 전역 1,525개 × unit 1,157개
    # = 176만 회를 헛돈다(정규식 치환 포함).
    _decl_types = _declared_type_map(gim)
    # 반환값이 있는 함수 집합. 이것도 unit 마다 안 바뀐다.
    _nonvoid = _nonvoid_function_names(function_details)
    # 피호출의 `[OUT]` 파라미터 맵. 위와 같은 자리다(unit 마다 안 바뀐다).
    _out_params = _out_param_names_by_function(function_details)
    # stub return 으로 되살린 칸 수 — 아래 요약 로그가 센다.
    _stub_added = 0
    # stub 출력 파라미터로 되살린 칸 수. **return 과 따로 센다** — 합치면 어느
    # 경로가 얼마를 냈는지 못 갈라서 회귀를 눈으로 못 본다.
    _stub_op_added = 0
    # SwUDS 대체가 지운 **파라미터**를 되돌린 칸 수. 위 둘과 또 따로 센다 —
    # 세 경로가 한 숫자에 뭉치면 어느 축이 죽었는지 로그로 못 본다.
    _param_restored = 0
    _param_restored_units = 0
    # 예산 절단 — 무경고로 버려지는 칸 수.
    _trunc_in = _trunc_out = _trunc_units = 0
    # 중간 마디 배열을 되살린 이름 수. 이 경로는 **틀린 이름을 고치는** 것이라
    # 0 이면 "고칠 게 없었다"인지 "배선이 끊겼다"인지 구분이 안 된다 → 요약에 싣는다.
    _mid_fixed = 0
    # 선언이 아니라 **관찰 첨자**로 폭을 정한 이름 수. 근거가 약한 경로이므로
    # 선언 크기 확장과 합쳐 세지 않는다 — 합치면 "선언으로 펼쳤다" 로 읽힌다.
    _obs_expanded = 0
    if sds_map is None:
        sds_map = _load_default_sds_map()
    units: List[Dict[str, Any]] = []
    _const_skipped = 0
    # SwUDS 대체가 **몇 unit 에 걸렸나**. 0 이면 UDS 를 못 읽었다는 뜻이고 산출물이
    # 달라지므로 아래 요약 로그에 싣는다(조용한 분기 금지 — 이 저장소가 여러 번 데었다).
    _uds_in_units = 0
    _uds_out_units = 0
    # 소스 `@asil` 주석과 SwUDS 표가 **다른 등급**을 말하는 unit. max 로 올려 쓰되
    # 조용히 넘어가지 않는다 — 어느 쪽이 낡았는지는 사람이 판단할 문제다.
    _asil_conflicts: List[str] = []
    # SDS 파티션 폴백이 **후보 등급이 갈리는데도** 하나를 집은 unit. 값은 예전 그대로지만
    # (대안 6개가 다 더 나빴다 — `_resolve_unit_asil` 주석) 그 사실을 침묵시키지는 않는다:
    # 사전 순서가 안전 등급을 정했다는 뜻이고, 안전 문서에서 그건 읽는 사람이 알아야 한다.
    _asil_weak: List[str] = []

    for fid, info in function_details.items():
        if not isinstance(info, dict):
            continue
        name = info.get("name", "")
        if not name:
            continue

        prototype = info.get("prototype") or f"void {name}(void)"
        inputs_raw = info.get("inputs") or []
        outputs_raw = info.get("outputs") or []
        globals_g = info.get("globals_global") or []
        globals_s = info.get("globals_static") or []

        input_vars: List[str] = _extract_var_names(inputs_raw)
        output_vars: List[str] = _extract_var_names(outputs_raw)

        # 파라미터 슬롯에서 온 **루트 이름**만 따로 붙잡아 둔다. 아래 SwUDS 대체는
        # `input_vars` 를 통짜로 교체하므로 여기서 안 잡으면 그대로 사라진다.
        # ⚠ 멤버 경로(`p[0].m`)는 뺀다 — 멤버까지 되돌리면 정밀도가 50% → 14.2% 로
        #   떨어진다(R24 P8 vs P6). SwUDS 가 root 를 적고 멤버를 골랐다면 **선별**이다.
        # ⚠ `[`·`(` 는 따로 안 막는다. `_extract_var_names` 가 배열 첨자를 떼고
        #   `->` 를 `[0].` 로 바꾸므로 **`[` 는 항상 `.` 를 동반**하고 `(` 는 shape
        #   검사에서 이미 막힌다(실측 KJPDS02_PV: `[` 단독 0건 · `(` 0건). 조건을
        #   더 얹으면 죽은 방어가 되어 뮤테이션이 통째로 살아남는다.
        # `return` 은 다르다 — 생산자가 반환 슬롯을 `inputs` 에 싣는 판이 실재하므로
        # (R23 이 `[OUT] U8 * p` 를 `inputs` 에서 만났다) 구조적으로 도달 가능하다.
        _param_roots: List[str] = [
            v for v in input_vars if v != _RETURN_VAR and "." not in v
        ]

        inp_set = set(input_vars)
        out_set = set(output_vars)

        globals_g_set = set(globals_g)

        for g in globals_g + globals_s:
            gn = _clean_global_name(g)
            if not gn or gn in _TYPE_NAMES:
                continue
            if len(gn) <= 2 or not re.match(r"[A-Za-z_]", gn):
                continue
            if _is_const_global(gn, gim):
                _const_skipped += 1
                continue
            if _LOCAL_TEMP_PATS.match(gn):
                continue

            is_in_global = g in globals_g_set

            role_in = False
            role_out = False

            # 방향 태그 — 앵커 매칭. `[INOUT]` 은 읽기·쓰기 **둘 다**다.
            _dir_tag = dir_tag(g)
            # ⚠ 간접 판정을 **파싱된 태그에서** 뽑는다. 예전의 `"[INDIRECT]" in tag` 는
            #   `[INDIRECT2]` 를 못 봐서 2홉이 직접 사용처럼 통과했다.
            is_indirect = _dir_tag.startswith("INDIRECT")
            if _dir_tag in {"IN", "INOUT"}:
                role_in = True
            if _dir_tag in {"OUT", "INOUT"}:
                role_out = True

            # 키워드 폴백 — 참조 SUDS 문서 경유 등 태그를 **안 붙이는** 생산자를 위해 남긴다.
            # ⚠ 예전엔 엔트리 **전체**를 substring 매칭했다(`"READ" in str(g).upper()`).
            #   그래서 **변수 이름 안의 글자**가 방향을 정했다 — `[INDIRECT] _ADC0STS.Bits.READY`
            #   의 `READY` 안에 `READ` 가 들어 있어 `role_in=True` 가 되고, 간접 억제는 아래
            #   `if not role_in and not role_out:` 블록 안에만 있으므로 **통째로 건너뛴다**.
            #   같은 부류의 substring 실패를 이 저장소가 `"[IN]" in "[INOUT] x"` 로 이미 겪었다.
            #   실측(2026-08-13, KJPDS02 전역 엔트리 6,711): 이름 안에 키워드가 든 엔트리 93건
            #   (63 unit · 변수 18종) — `[INDIRECT*]` 27건은 억제를 건너뛰고, `[OUT]`+READ ·
            #   `[IN]`+WRITE 29건은 파서 태그를 **뒤집어** 같은 이름이 양쪽 열에 실렸다.
            #   대표: `u8g_SysUds_WriteData` 24 · `_ADC0STS.Bits.READY` 7 · `u8g_SleepReady_F` 3.
            # 그래서 **선두 토큰**만 본다. 이 표기를 내는 생산자는 키워드를 앞에 놓는다
            # (`_clean_global_name` 이 마지막 토큰에서 이름을 뽑으므로 그래야 성립한다).
            # 실측: 이 프로젝트에서 선두 토큰 키워드는 **0건** — 앵커로 좁혀도 잃는 게 없다.
            # ⚠ "태그가 있으면 폴백을 건너뛴다"는 게이트를 따로 두지 **않았다**. 태그된
            #   엔트리는 `[` 로 시작하니 앵커에 애초에 안 걸린다 — 그 게이트는 위 93건을
            #   앵커와 **똑같이** 막아서, 둘 다 두면 하나를 지워도 테스트가 통과한다
            #   (죽은 방어). 기제는 하나로 두고 그 하나를 뮤테이션으로 지킨다.
            _kw = _KEYWORD_DIR_PAT.match(str(g))
            if _kw:
                _k = _kw.group(1).upper()
                if _k in {"READ", "RHS"}:
                    role_in = True
                if _k in {"WRITE", "LHS"}:
                    role_out = True

            # 프리픽스 휴리스틱 — **태그를 못 받은 엔트리 전용**이다. 이름 규약으로
            # 방향을 추측하는 것이라, 방향 근거가 있는 엔트리에 덮어씌우면 안 된다.
            #
            # ⚠ `[INDIRECT*]` 는 "이 함수 본문엔 없고 **피호출 함수 안에서** 쓰인다"는
            #   뜻이라 방향 근거가 **아예 없다**. 그런데 예전엔 이 블록을 그대로 태워서
            #   `if not is_indirect` 가드를 다섯 군데 흩뿌려 놓았고, 그 가드는 전부
            #   `role_in` 에만 붙어 있었다 — 즉 **입력은 막고 기대결과는 무조건 냈다**.
            #   `[INDIRECT] u8s_X` 는 기대결과로 나가고 `[INDIRECT] u8g_X` 는 통째로
            #   사라지는, 접두사가 방향을 정하는 비대칭이었다.
            #   실측(2026-08-14, KJPDS02_PV 정본 1,005 unit): 오로지 `[INDIRECT*]`
            #   엔트리에서만 온 기대결과 칸 **1,777개 중 정본과 일치 0개**(정확 일치도
            #   뿌리 일치도 0). 그중 798칸은 **정본이 기대결과 열을 통째로 비워둔**
            #   unit 에 채워 넣은 것이다. 반대로 우리가 어느 열에도 안 낸 간접 이름
            #   1,648개도 정본엔 입력·기대 **양쪽 모두 0** 이다 — 정본은 간접 접근
            #   전역을 애초에 적지 않는다. 억제의 대가가 **0** 이라는 뜻이다
            #   (`const` 전역 419칸 때와 같은 모양이다).
            #   간접 전역은 여기서 버리는 게 아니라 아래 `indirect_vars` 로 가서
            #   GLOBAL/VOID 시험 전략의 재료가 된다 — 열에 이름을 박지 않을 뿐이다.
            # ⚠ 가드를 한 조건으로 모은 것도 의도다. 흩어 놓으면 하나를 지워도 나머지
            #   넷이 같은 케이스를 막아 뮤테이션이 통째로 생존한다(이 저장소가 직전
            #   라운드에서 겪은 '겹친 기제' 실패).
            if not role_in and not role_out and not is_indirect:
                if gn.startswith(_OUTPUT_PREFIXES):
                    role_out = True
                elif gn.startswith(_INPUT_PREFIXES):
                    role_in = True
                elif _REG_PAT.match(gn):
                    role_in = True
                    role_out = True
                elif gn.startswith(("g_", "r_")):
                    role_in = True
                    role_out = True
                elif not is_in_global:
                    role_out = True
                else:
                    role_in = True

            # ⚠ 표기 정합은 **맨 마지막**에만 한다. 위의 `_is_const_global`·
            #   `_LOCAL_TEMP_PATS`·프리픽스 판정은 전부 C 이름(`gn`)을 키로 쓰므로
            #   먼저 바꾸면 그 조회들이 조용히 빗나간다.
            gd = _vc_pointer_notation(gn)
            if role_in and gd not in inp_set:
                input_vars.append(gd)
                inp_set.add(gd)
            if role_out and gd not in out_set:
                output_vars.append(gd)
                out_set.add(gd)

        component = ""
        module = info.get("module_name", "")
        if fid and re.match(r"SwUFn_\d+", fid):
            comp_num = fid.replace("SwUFn_", "")[:2]
            component = f"SwCom_{comp_num}"
            if module:
                component = f"{component}\n({module})"

        # Attempt to resolve SRS requirement IDs via SDS partition map
        srs_req_ids = _resolve_srs_req_ids_for_function(name, sds_map)

        if not output_vars:
            ret_type = _infer_return_type(prototype)
            if returns_value(ret_type):
                # 정본 표기와 같은 이름을 쓴다 — `return_<함수명>` 은 정본 어디에도 없다.
                output_vars.append(_RETURN_VAR)
                out_set.add(_RETURN_VAR)

        # ── SwUDS 가 적은 이름으로 **대체** ──────────────────────────────────
        # SUTS 는 SwUDS 를 근거로 만드는 문서다. 정본의 Inpt/ExpR 열은 소스 파싱이
        # 아니라 SwUDS 의 `[ Input/Output Parameters ]` 표에서 온다.
        # 실측(2026-08-14, KJPDS02_PV · 첨자 지운 이름 집합 기준):
        #                       입력 재현율·과다      기대 재현율·과다
        #   소스 파싱(옛 판)      84.3% · 617          84.0% · 550
        #   **SwUDS**            88.0% · 110          83.6% · 348
        #   SwUDS + 우리 `return` 표기                 **94.1%** · 358
        # 더 많이 맞히면서 과다는 1/6 이다.
        # ⚠ 대체는 **원소 확장 전에** 한다. 뒤에 하면 UDS 이름이 배열이어도 안 펼쳐져
        #   정본 입도(`buf[0]`…)와 어긋난다.
        # ⚠ UDS 가 그 축에 **아무것도 안 적었으면 우리 것을 유지**한다. 빈 목록으로
        #   덮으면 "UDS 에 근거가 없다"와 "UDS 가 0개라고 했다"가 같아진다.
        # ⚠ 정본이 쓰는 VectorCAST 표기(`return` · `f() p[0]() m`)는 UDS 에 없다 —
        #   기대 축에서 그것만 남긴다(이게 기대 재현율 83.6→94.1%p 의 정체다).
        _uds_rec = resolve_unit_io(uds_io_map, name)
        if _uds_rec is not None:
            # ⚠ UDS 는 반환값을 `Return` 으로, 정본 SUTS 는 `return` 으로 적는다.
            #   대소문자만 다른 같은 것이라 그대로 두면 **한 행에 반환값이 두 번**
            #   실리고 그중 하나는 정본에 없는 이름이 된다(실측 284칸 = 이 축 신규
            #   과다의 85%). 표기는 `_RETURN_VAR` **한 곳**으로 모은다.
            def _norm_uds(x: str) -> str:
                y = _vc_pointer_notation(x)
                return _RETURN_VAR if y.strip().lower() == _RETURN_VAR else y

            _u_in = [_norm_uds(x) for x in (_uds_rec.get("inputs") or []) if x]
            _u_out = [_norm_uds(x) for x in (_uds_rec.get("outputs") or []) if x]
            if _u_in:
                input_vars = list(dict.fromkeys(_u_in))
                inp_set = set(input_vars)
                _uds_in_units += 1
                # ── SwUDS 가 빠뜨린 **파라미터**를 되돌린다 ──────────────
                # 통짜 교체라 SwUDS 표에 없는 파라미터는 시험 입력에서 사라진다.
                # 파라미터는 정의상 시험 입력이므로 그 누락은 **under-testing** 이다.
                # 실측(R24, KJPDS02_PV — 대체가 지운 입력 527칸 기준):
                #   되살릴 대상          생산   적중   과다   정밀도
                #   전부(합집합)          527     37    490     7.0%   ← 기각
                #   전역만                409     16    393     3.9%   ← 기각
                #   파라미터 멤버 포함     118     21     97    17.8%
                #   **파라미터 루트만**    22     11     11    50.0%   ← 채택
                #   그중 SwUDS 가 root 를 아예 안 적은 것  5/5 = **100%**
                # 실제 사례가 규칙을 설명한다 — SwUDS 쪽 오타·누락이다:
                #   `prv_ComputeQ15Ratio`      파라미터 `val`  ↔ SwUDS `Val`
                #   `s_ApplyTemperatureCompensation` `s16_Ratio` ↔ SwUDS `s16t_Ratio`
                #   `g_Lib_SafeWriteQueue_EnqueueWrite` 콜백 2개를 SwUDS 가 누락
                # ⚠ **입력 열 전용**이다. 같은 규칙을 기대 열에 걸면 정밀도 1.2%
                #   (생산 86 · 적중 1) — 정본 ExpR 은 파라미터를 그렇게 안 적는다.
                # ⚠ 멤버 경로까지 되돌리지 않는다. SwUDS 가 root 를 적고 멤버를
                #   골랐다면 그건 **선별**이고, 거기 우리가 멤버를 더 얹는 건 추측이다.
                _restore = [p for p in _param_roots if p not in inp_set]
                if _restore:
                    input_vars = list(dict.fromkeys(input_vars + _restore))
                    inp_set = set(input_vars)
                    _param_restored += len(_restore)
                    _param_restored_units += 1
            if _u_out:
                _keep_vc = [v for v in output_vars if v == _RETURN_VAR or "()" in v]
                output_vars = list(dict.fromkeys(_u_out + _keep_vc))
                out_set = set(output_vars)
                _uds_out_units += 1

        # ── 피호출 함수의 반환값을 시험 입력으로 ────────────────────────
        # ⚠ 위 SwUDS 대체가 `input_vars` 를 **통째로 교체**하므로 반드시 그 **뒤**다.
        #   그리고 예산(`max_inp`) 계산 **앞**이라야 배열 확장이 이 칸까지 셈한다.
        # ⚠ 기대 열에는 넣지 않는다 — 정본 ExpR 의 stub return 은 0칸이다.
        _stubs = _stub_return_names(info.get("calls_list"), _nonvoid, own=str(name or ""))
        if _stubs:
            _before_stub = len(input_vars)
            input_vars = list(dict.fromkeys(list(input_vars) + _stubs))
            inp_set = set(input_vars)
            _stub_added += len(input_vars) - _before_stub
        # ── 그 stub 이 출력 파라미터에 써 넣는 값도 시험 입력이다 ────────
        # ⚠ 반환값 뒤에 둔다 — 정본은 같은 피호출의 `() return` 을 먼저 적는다.
        #   앞에 두면 예산이 빠듯한 unit 에서 순서만으로 맞춤이 뒤바뀐다.
        _stub_ops = _stub_out_param_names(info.get("calls_list"), _nonvoid, _out_params, own=str(name or ""))
        if _stub_ops:
            _before_op = len(input_vars)
            input_vars = list(dict.fromkeys(list(input_vars) + _stub_ops))
            inp_set = set(input_vars)
            _stub_op_added += len(input_vars) - _before_op

        max_inp = _INPUT_COL_END - _INPUT_COL_START + 1
        max_out = _OUTPUT_COL_END - _OUTPUT_COL_START + 1

        # 배열을 원소 단위로 펼친다(정본과 같은 입도). 입력·기대 **양쪽** 이다 —
        # 실측상 같은 unit 에서 양쪽에 펼쳐진 배열이 120건이라, 한쪽만 펼치면 한 행
        # 안에서 같은 변수가 다른 이름으로 두 번 나온다.
        _sizes = _array_sizes(
            inputs_raw, outputs_raw, globals_g, globals_s,
            globals_info=gim, struct_members=struct_members,
        )
        # 중간 마디는 unit 마다 파라미터 타입이 달라 **여기서** 만든다(전역만인
        # `_root_sizes` 와 달리 루프 밖으로 못 뺀다).
        _mid_in: Dict[str, Tuple[int, Tuple[int, ...]]] = {}
        _mid_out: Dict[str, Tuple[int, Tuple[int, ...]]] = {}
        if struct_members:
            _rtypes = _root_type_hints(
                inputs_raw, outputs_raw, globals_g, globals_s, declared_types=_decl_types
            )
            _mid_in = _mid_member_sizes(input_vars, _rtypes, struct_members)
            _mid_out = _mid_member_sizes(output_vars, _rtypes, struct_members)
            _mid_fixed += len(_mid_in) + len(_mid_out)
        # 선언 크기가 없는 **포인터 버퍼**의 폭 — 본문에서 관찰된 리터럴 첨자.
        # 방향 태그로 열이 갈린다(`_observed_idx_map` 독스트링에 실측 표).
        _raws = [inputs_raw, outputs_raw, globals_g, globals_s]
        _obs_in = _observed_idx_map(_raws, {"IN"})
        _obs_out = _observed_idx_map(_raws, {"OUT"})
        input_vars, _in_exp = _expand_array_entries(
            input_vars, _sizes, max_inp, root_sizes=_root_sizes, mid_sizes=_mid_in,
            observed_idx=_obs_in,
        )
        output_vars, _out_exp = _expand_array_entries(
            output_vars, _sizes, max_out, root_sizes=_root_sizes, mid_sizes=_mid_out,
            observed_idx=_obs_out,
        )
        _obs_expanded += len(_in_exp.get("observed") or []) + \
            len(_out_exp.get("observed") or [])

        # ── ASIL — `Safety Related` 칸(O/X)의 근거 ─────────────────────────
        #
        # 우선순위: **max(소스 `@asil` 주석, SwUDS 표)** > SDS 파티션 퍼지매칭.
        #
        # 예전엔 소스 태그가 없으면 곧장 `_resolve_unit_asil` 로 갔는데, 그건 모듈명을
        # **부분문자열**로 SDS 파티션에 맞추는 판정이다(`nc in nk or nk in nc`, 첫
        # 일치 채택). 그 결과가 정본과 이만큼 어긋났다 —
        # 실측(2026-08-14, KJPDS02_PV · 정본이 `Safety Related` 를 **채운** 868칸):
        #
        #   출처            건수   일치            방향오류
        #   SDS 퍼지매칭     666    489 (73.4%)    **over 88**   ← 비안전을 안전으로
        #   소스 `@asil`     202    200 (99.0%)    under 2       ← 안전을 비안전으로
        #
        # 같은 unit 을 SwUDS 표의 ASIL 로 채우면 **방향 오류 0**(퍼지매칭 구간 663/666,
        # 소스 태그 구간 201/202). 교차표에 A→X · QM→O 가 **한 건도 없다**:
        #   UDS A → 정본 O 562 · 정본 빈칸 137 · 정본 X **0**
        #   UDS QM → 정본 X 302 · 정본 O **0**
        # (정본 빈칸 137 은 한 덩어리 연속 구간[행 496~632, MotorCtrl 계열]이라
        #  정본 자신의 미기재다. 우리는 근거가 있으므로 채운다.)
        #
        # 정책 비교(같은 868칸 기준): 현재 689(79.4%) · 소스>UDS 864 · **max 865(99.7%)**
        # · UDS만 855. max 를 고른 이유는 두 가지다:
        #   ① under-classification(안전 요구 면제)이 ISO 26262 에서 더 위험한 방향인데
        #      max 는 등급을 **내리지 않는다**.
        #   ② 이 저장소가 추적성 배선에서 이미 같은 결론을 냈다(first-wins 로 하향
        #      101건 → max 병합).
        # 실측 충돌은 **1건**뿐이고(`s_ApiOut_u8bit_DataUpdate_A` 소스 QM vs UDS A)
        # 정본은 `O` 다 — UDS 가 맞다. 그래도 충돌은 **세어서 보고**한다(조용한 승격 금지).
        #
        # ⚠ 등급 비교는 `report_gen.requirements._asil_max_of` **단일 출처**로 한다.
        #   이 저장소엔 ASIL 순위표가 이미 여러 벌 있고(하나는 정렬용 역순이다) 여기
        #   또 만들면 다음에 한쪽만 고쳐진다.
        _src_asil = str(info.get("asil") or "").strip()
        # (R70 N83) 그 값이 소스 `@asil` 인지 저장소 override 스냅샷(`docs/uds_function_swcom_override.json`,
        #   프로젝트 확인 없음)인지는 소스 단계 라벨(`asil_source`, R68)이 안다. 예전엔 둘 다 "source" 였다 —
        #   KJPDS02 에서 override 가 준 228 unit 의 등급이 소스 근거로 표시됐고, 준비 게이트의 근거 축도 그렇게 읽었다.
        _src_kind = "override" if str(info.get("asil_source") or "") == "override" else "source"
        _uds_asil = str((_uds_rec or {}).get("asil") or "").strip()
        # ⚠ 충돌은 **양쪽 다 실제 등급일 때만**이다. `TBD`·`N/A` 는 "근거 없음"이지
        #   반대 주장이 아니다. 문자열이 비었는지만 보면 `TBD vs A` 가 충돌로 잡혀
        #   경고가 **778건**을 외친다(실측) — 그러면 진짜 충돌 1건이 그 안에 묻힌다.
        #   늑대를 778번 외치는 경고는 없는 것만 못하다.
        _src_grade, _uds_grade = _asil_max_of([_src_asil]), _asil_max_of([_uds_asil])
        if _src_grade and _uds_grade and _src_grade != _uds_grade:
            _asil_conflicts.append(
                f"{name}({'소스' if _src_kind == 'source' else 'override'} {_src_grade} vs UDS {_uds_grade})")
        asil = _asil_max_of([_src_asil, _uds_asil])
        _asil_evidence = (f"uds+{_src_kind}" if _src_grade and _uds_grade
                          else "uds" if _uds_grade else _src_kind if _src_grade else "")
        if not asil:
            # SDS 파티션 폴백 — 값은 예전과 같다. 다만 그 값이 **모듈명 부분문자열
            # 매칭의 첫 일치**라는 사실과, 후보 등급이 갈렸는지를 함께 받는다.
            _sds_asil, _asil_evidence = _resolve_unit_asil(info, sds_map)
            asil = _sds_asil or _src_asil or "TBD"
            if _asil_evidence == "sds-fuzzy-conflict":
                _asil_weak.append(name)

        # Collect indirect (global) vars for GLOBAL/VOID strategies
        indirect_vars: List[str] = []
        for g in globals_g + globals_s:
            gn = _clean_global_name(g)
            # ⚠ 2홉(`[INDIRECT2]`)도 간접이다 — 여기서 빠지면 GLOBAL/VOID 전략이
            #   간접 변수를 하나도 못 받는다.
            if gn and dir_tag(g).startswith("INDIRECT") and gn not in inp_set and gn not in out_set:
                if gn not in indirect_vars and len(indirect_vars) < 5:
                    indirect_vars.append(gn)

        # 이 unit 이 온 파일의 시험 범위 판정(`O`/`X`/빈값). 값을 거르지는 **않는다** —
        # SUTS 에서 시험을 빼는 건 사람이 할 결정이다. 다만 조용하면 그 결정 기회가
        # 사라지므로 unit 에 남기고 아래 요약 로그에 센다.
        # ⚠ 아래 `input_vars[:max_inp]` 는 **경고 없이** 자른다. 배열 확장은
        #   `array_expansion.skipped` 로 보고하지만 이 최종 절단은 어디에도 안 남아,
        #   "정본과 다르다"의 원인을 못 짚는 침묵 표면이었다. 세어서 요약에 낸다.
        _trunc_in += max(0, len(input_vars) - max_inp)
        _trunc_out += max(0, len(output_vars) - max_out)
        if len(input_vars) > max_inp or len(output_vars) > max_out:
            _trunc_units += 1
        _verify = component_verify_of(info.get("file"), _cmap)
        units.append({
            "verify_scope": _verify,
            "fid": fid,
            "name": name,
            "source_text": info.get("source_text") or "",
            "source_path": info.get("source_path") or "",
            "source_unavailable_reason": info.get("source_unavailable_reason") or "",
            # 원문이 레코드에 없으면(R80: 파일당 `source_files` 맵으로 옮김) `attach_unit_sources` 가 붙일 때까지 미완결이다 —
            #   붙이지 않은 호출자가 "완결된 빈 원문" 으로 오독하지 않게(리뷰 R3 Info).
            "source_text_complete": bool(info.get("source_text")) and info.get("source_text_complete", True),
            "prototype": prototype,
            "component": component,
            "input_vars": input_vars[:max_inp],
            "output_vars": output_vars[:max_out],
            # 무엇을 펼쳤고 무엇을 예산 때문에 못 펼쳤나. 건너뛴 배열은 정본보다
            # **입도가 낮은** 칸이 되므로 조용히 두면 "정본과 다르다"의 원인을 못 짚는다.
            "array_expansion": {"input": _in_exp, "output": _out_exp},
            "indirect_vars": indirect_vars,
            "logic_flow": info.get("logic_flow") or [],
            "calls_list": info.get("calls_list") or [],
            # (R74) SwUDS `Description` 행이 있고 더 길면 그것 — 예전 보강(`_load_uds_descriptions`)은 문단 heading 을 키로 써
            #   `SwUFn_0101: main` 꼴 문서에서 0건이었다(KJPDS02 실측: 989 함수 전부 Description 보유).
            "description": max(str(info.get("description") or ""), str((_uds_rec or {}).get("description") or ""), key=len),
            # (R73 N92) enum 타입 변수의 닫힌 값 집합(입력·기대·간접 전역) — 시퀀스가 경계값 대신 열거자 값을 쓴다.
            "value_domains": _unit_value_domains(
                info, gim, list(input_vars[:max_inp]) + list(output_vars[:max_out]) + list(indirect_vars)),
            # (R74) SwUDS 파라미터 표의 타입·Value Range — 설계서가 적은 범위가 타입 전폭보다 먼저다.
            "uds_param_info": _unit_uds_param_info(
                _uds_rec, list(input_vars[:max_inp]) + list(output_vars[:max_out]) + list(indirect_vars)),
            "asil": asil,
            # 그 등급이 **어디서 왔나**. `sds-fuzzy-conflict` 는 "모듈명 부분문자열
            # 매칭에서 후보 등급이 갈렸고 그중 하나를 집었다" 는 뜻이다.
            "asil_evidence": _asil_evidence,
            # (R70 N83) 소스에 없고 override 스냅샷에만 있는 함수 — 시험 대상인지는 사람이 정한다(P7). 세어서 보고한다.
            "override_only": bool(info.get("override_only")),
            # (R71 N77) 파라미터 선언 타입 — 시퀀스 생성이 전역 타입 캐시 위에 얹어 쓴다(`bool`·`U16*`·구조체 포인터).
            #   (R73 N92) 선언이 모르는 타입(typedef)일 때만 소스 단계가 풀어 둔 원 선언(`param_base_types`)을 쓴다.
            "param_types": {
                _pn: _prefer_known_decl(_pd, (info.get("param_base_types") or {}).get(_pn))
                for _pn, _pd in _param_decl_types(inputs_raw, outputs_raw).items()
            },
            "srs_req_ids": srs_req_ids,
            "precondition": info.get("precondition", ""),
        })

    units.sort(key=lambda u: u["fid"])
    # 배열 확장 집계. 건너뛴 게 있으면 WARNING 으로 올린다 — 예산 때문에 정본보다
    # 입도가 낮아진 칸이 있다는 뜻이고, 그건 조용하면 안 된다.
    _exp_n = sum(len(u["array_expansion"]["input"]["expanded"])
                 + len(u["array_expansion"]["output"]["expanded"]) for u in units)
    _skip = [(u["name"], s["name"], s["elements"], s["remaining"])
             for u in units
             for axis in ("input", "output")
             for s in u["array_expansion"][axis]["skipped"]]
    # ⚠ `globals_info_map` 이 없으면 const 판정 자체를 못 한다 — 같은 소스라도 산출물이
    #   달라지므로 **명시**한다(조용한 분기는 이 저장소가 여러 번 데었다).
    _const_note = (
        f" | const 전역 억제 {_const_skipped}칸" if gim
        else " | ⚠globals_info_map 없음 → const 억제 안 함"
    )
    # SwUDS 대체가 안 걸렸으면 **소스 파싱 결과가 그대로 나간다** — 산출물이 달라지므로
    # 조용히 두지 않는다(정본 대비 과다가 6배 나던 옛 판이 그 상태다).
    _const_note += (
        f" | SwUDS 이름 대체 입력 {_uds_in_units}/{len(units)} · 기대 {_uds_out_units}"
        if uds_io_map else " | ⚠SwUDS 입출력 맵 없음 → 소스 파싱 이름 사용"
    )
    # 대체가 지운 파라미터를 되돌린 양. **SwUDS 대체가 걸린 unit 이 있을 때만** 의미가
    # 있으므로 0 을 "고칠 게 없었다"로 읽히게 두지 않는다 — 대체 자체가 없었으면 그렇게 적는다.
    _const_note += (
        f" | 대체가 지운 파라미터 복원 {_param_restored}칸({_param_restored_units} unit)"
        if _uds_in_units else " | ⚠SwUDS 입력 대체 0 unit → 파라미터 복원 판정 안 함"
    )
    # 중간 마디 배열 복원. 이건 입도 조정이 아니라 **불성립 이름 교정**이라
    # (배열에 `.멤버` 는 못 붙인다) 0 건이면 "고칠 게 없었다"인지 "배선이 끊겼다"인지
    # 구분이 안 된다 — 구조체 맵 유무와 함께 남긴다.
    _const_note += (
        f" | 중간마디 배열 복원 {_mid_fixed}칸"
        if struct_members else " | ⚠구조체 멤버 맵 없음 → 중간마디 배열 복원 안 함"
    )
    # 관찰 첨자로 폭을 정한 포인터 버퍼. **선언 크기 확장과 따로** 센다 — 근거가
    # 본문 등장 첨자뿐이라 배열보다 좁을 수 있고, 그 사실이 수치에 남아야 한다.
    _const_note += f" | 관찰첨자 확장 {_obs_expanded}건"
    # ASIL 이 소스 주석과 문서에서 갈린 unit. max 로 올려 썼다는 사실을 남긴다 —
    # 어느 쪽이 낡았는지 판단은 사람 몫이고, 조용하면 그 판단 기회가 사라진다.
    if _asil_weak:
        _const_note += (
            f" | ⚠ASIL 근거 약함 {len(_asil_weak)}건(SDS 모듈명 부분문자열 매칭에서 후보 등급이"
            f" 갈림): " + ", ".join(_asil_weak[:3]) + (" …" if len(_asil_weak) > 3 else "")
        )
    if _asil_conflicts:
        _const_note += (
            f" | ⚠ASIL 소스↔SwUDS 충돌 {len(_asil_conflicts)}건(높은 등급 채택): "
            + ", ".join(_asil_conflicts[:3])
            + (" …" if len(_asil_conflicts) > 3 else "")
        )
    # (R70 N83) 등급의 근거 분포와, 소스에 없는 override 전용 unit. 둘 다 조용하면 "소스 근거" 로 읽힌다.
    _ev_dist: Dict[str, int] = {}
    for _u in units:
        _k = str(_u.get("asil_evidence") or "") or "none"
        _ev_dist[_k] = _ev_dist.get(_k, 0) + 1
    _const_note += " | ASIL 근거 분포 " + (
        ", ".join(f"{k} {v}" for k, v in sorted(_ev_dist.items())) if _ev_dist else "없음(unit 0)")
    _ovr_only_units = [u["name"] for u in units if u.get("override_only")]
    if _ovr_only_units:
        _const_note += (
            f" | ⚠override 스냅샷 전용 unit {len(_ovr_only_units)}개(소스에 없음 — prototype 은 자리표시): "
            + ", ".join(_ovr_only_units[:3]) + (" …" if len(_ovr_only_units) > 3 else "")
        )
    # 시험 범위 불일치 — `component_map` 이 면제(X)로 적은 파일에서 온 unit.
    # ⚠ `uds_generator` 의 파일 수집은 X 를 건너뛰지만 **AST 파서 경로는 루트를 따로
    #   훑어 그 필터를 안 탄다**. 그래서 X 유래 함수가 여기까지 온다. 실측
    #   (KJPDS02_PV): 정본에 없는 unit 152개 중 45개가 X 유래 — 정본은 1,005개 중
    #   24개만 X 다. 지우지 않고 **세어서 보고**한다(범위 결정은 사람 몫).
    _scope_x = [u["name"] for u in units if u.get("verify_scope") == "X"]
    _scope_note = (
        f" | ⚠시험 면제(component_map verify=X) 파일 유래 unit {len(_scope_x)}개: "
        + ", ".join(_scope_x[:3]) + (" …" if len(_scope_x) > 3 else "")
    ) if _scope_x else (
        "" if _cmap else " | ⚠component_map 없음 → 시험 범위 판정 안 함"
    )
    # ⚠ 비-void 함수가 0 이면 "stub 0칸" 이 아니라 **판정 못 함**이다 — 파서가
    #   `[OUT] return` 을 안 냈다는 뜻이라 축이 통째로 죽는다. 구분해서 말한다.
    _const_note += (
        f" | stub return {_stub_added}칸(비-void {len(_nonvoid)}개)"
        if _nonvoid else " | ⚠비-void 함수 0개 → stub return 판정 안 함"
    )
    # ⚠ return 과 **합쳐 세지 않는다** — 두 경로는 근거가 같지만 정밀도가 다르고
    #   (42.8% vs 34.3%), 합치면 어느 쪽이 회귀했는지 로그로 못 가른다.
    _const_note += (
        f" | stub 출력파라미터 {_stub_op_added}칸(대상 함수 {len(_out_params)}개)"
        if _out_params else " | ⚠[OUT] 파라미터를 가진 함수 0개 → stub 출력파라미터 판정 안 함"
    )
    if _trunc_units:
        _const_note += (
            f" | ⚠예산 절단 {_trunc_units}unit(입력 {_trunc_in}칸·기대 {_trunc_out}칸)"
        )
    _const_note += _scope_note
    (_logger.warning if _skip else _logger.info)(
        "Collected %d unit functions | 배열 확장 %d건%s%s",
        len(units), _exp_n,
        ("  ⚠예산 부족으로 미확장 %d건: %s" % (
            len(_skip),
            ", ".join(f"{u}::{n}({k}원소, 여유 {r})" for u, n, k, r in _skip[:3]),
        )) if _skip else "",
        _const_note,
    )
    return units


def _infer_return_type(prototype: str) -> str:
    """Extract the return type from a C function prototype string."""
    proto = prototype.strip()
    m = re.match(r"^([\w\s\*]+?)\s+\w+\s*\(", proto)
    if not m:
        return "void"
    ret = m.group(1).strip()
    ret = re.sub(r"\b(static|inline|extern|const|volatile)\b", "", ret).strip()
    return ret if ret else "void"


# 파서가 이름 **뒤에** 붙이는 주석형 꼬리(`_format_param_entry`).
#   `u8g_Hash (idx: u8t_Index)` · `ctx (range: 0x0 ~ 0xFFFFFFFF)` · `div (divisor: no 0)`
# ⚠ 이름은 마지막 토큰에서 뽑는데 이 꼬리를 안 떼면 **꼬리가 이름이 된다**:
#   · `(idx: u8t_Index)` → 이름이 `u8t_Index)` → `_LOCAL_TEMP_PATS`(`u8t_`)에 걸려 **전역이 통째로 사라진다**
#   · `(range: … 0xFFFFFFFF)` → 이름이 `0xFFFFFFFF)` → 식별자가 아니라 **파라미터가 통째로 사라진다**
# 실측(2026-08-12, KJPDS02 750함수): 입력 0개 unit 221 건 중 **57 건**이 이 경로였다.
# `s_sha256_transform` 은 정본이 입력 9개를 적는데 우리는 0개였다.
# ⚠ 꼬리 키워드는 **한 곳**에서만 정의한다. 아래 두 정규식이 같은 목록을 각자 들고
#   있으면 새 꼬리를 추가할 때 하나만 고쳐지고, 그 꼬리가 그대로 **이름이 된다**.
#   (같은 부류의 실패를 이 저장소가 `[INOUT]`·`[INDIRECT2]` 로 두 번 겪었다.)
# ⚠ 정의는 **생산자**(`report_gen/function_analyzer.py`)에 있다. 여기에 사본을 두면
#   새 꼬리를 추가할 때 한쪽만 고쳐지고 그 꼬리가 그대로 이름이 된다.
#   중첩 괄호 처리도 그쪽 `split_param_annotations` 한 곳에만 있다:
#   `[^)]*\)` 는 첫 `)` 에서 멈추므로 `$` 앵커 정규식만으로는 꼬리가 안 떨어지고,
#   마지막 토큰이 `))` 가 되어 이름 필터에서 탈락 → **진짜 전역이 사라진다**
#   (실측 2026-08-12: `u8s_DeviceTypeChk_*` 2건).


def _strip_param_annotations(s: str) -> str:
    """이름 뒤 주석형 꼬리를 **전부** 뗀다(여러 개가 이어 붙고, 안에 괄호가 중첩된다)."""
    return split_param_annotations(s)[0]


# 파라미터 문자열이 **선언이 아닌** 경우. 상위 파서가 주석 블록을 통째로 파라미터 하나로
# 딸려보내는 일이 있다(Processor Expert 계열 `*_GetVal` 실측 40건):
#   `[IN] void) ** This method is implemented as a macro. … // if (Val == (U8) TRUE (range: …)`
# ⚠ 이걸 그냥 두면 마지막 토큰인 **`TRUE` 가 변수명이 된다** — 없는 입력을 지어내는 것이라
#   빈 칸보다 나쁘다(꼬리 주석 제거를 넣자마자 실제로 3건 발생했다). 선언이 아니면 **버린다**.
#   버려진 건 게이트가 `param_string_unusable` 로 보고한다 — 침묵시키지 않는다.
# **선언자 모양** 검사. 타입·이름 토큰과 `*` `[]` `.` `->` 만 허용한다.
# 괄호·대입·세미콜론이 있으면 선언이 아니다(주석 잔해나 코드 조각이 딸려온 것).
#   OK : `l_u8 msg_length` · `const l_u8* const data` · `q * queue->queue_tail` · `buf[8]`
#   NG : `void) ** This method is implemented as a macro. …` · `if positive = 0 l_u8 err`
# ⚠ 여기서 통과시키면 **마지막 토큰이 이름이 된다** — 즉 없는 입력을 지어낸다. 빈 칸보다
#   나쁘다(꼬리 주석 제거를 처음 넣었을 때 실제로 `TRUE` 3건이 그렇게 들어갔다).
#   버려진 건 게이트가 `param_string_unusable` 로 보고한다 — 침묵시키지 않는다.
_PARAM_DECL_SHAPE = re.compile(r"[A-Za-z_][\w\s\*\[\]\.>-]*")
_PARAM_DECL_MAX_LEN = 120


# 반환값 슬롯. 생산자 5곳이 `[OUT] return <타입>` 형태로 낸다(`function_analyzer`·
# `backend/helpers/common`·`uds_generator`·`tools/generate_uds_local`·아래 3179행) —
# **그 계약은 건드리지 않는다**. 문제는 소비처였다: `^return\s+` 를 지우고 마지막 토큰을
# 취해 **타입 이름을 변수로** 냈다(실측 KJPDS02_PV 기대열 287건: `U8` 144 · `U16` 62 ·
# `S16` 32 · `l_u8` 19 …). 정본은 반환값을 **`return`** 이라고 적는다(기대 엔트리 5,389
# 중 `return` 290 · `return[0]` 7).
_RETURN_SLOT_RE = re.compile(r"^return\b", re.I)
_RETURN_VAR = "return"


# 포인터 표기. 정본(VectorCAST)은 포인터 뒤에 **1원소 이상의 배열**을 잡아주므로
# `p[0]` · `p[0].m` 으로 적는다. 우리 생산자는 C 문법 그대로 `p` · `p->m` 을 낸다 —
# **같은 대상을 다르게 부르는 것**이라, 표기만 맞추면 과다와 미달이 동시에 닫힌다.
# 실측(KJPDS02_PV 시뮬): 입력 163칸 · 기대 124칸이 과다→일치로 이동, **잃은 일치 0**.
# ⚠ 생산자 계약(`[IN] word * Values`)은 건드리지 않는다 — UDS 상세설계엔 C 표기가 맞다.
#   `return` 슬롯과 같은 방식이다(소비처에서만 교정).
_ARROW_RE = re.compile(r"\s*->\s*")


def _vc_pointer_notation(name: str) -> str:
    """``p->m`` → ``p[0].m``. 화살표가 없으면 원본 그대로."""
    s = str(name or "")
    return _ARROW_RE.sub("[0].", s) if "->" in s else s


def _extract_var_names(raw_list: List[str]) -> List[str]:
    """Extract clean variable names from [IN]/[OUT] tagged param strings."""
    names: List[str] = []
    for raw in raw_list:
        s = str(raw).strip()
        s = re.sub(r"^\[(?:IN|OUT|INOUT)\]\s*", "", s)
        if _RETURN_SLOT_RE.match(s):
            if _RETURN_VAR not in names:
                names.append(_RETURN_VAR)
            continue
        s = re.sub(r"^return\s+", "", s, flags=re.I)
        # 파라미터 앞에 붙은 설명 주석(`/* [IN] … */ l_u8 msg_length`)을 지운다.
        # 생산자(`_parse_signature_params`)가 2026-08-12부터 안 붙이지만, **캐시된 산출물과
        # 참조 SUDS 문서 경유분에는 남아 있다** — 소비처에서도 한 번 더 지워야 회복된다.
        s = _strip_param_annotations(blank_c_comments(s).strip())
        if len(s) > _PARAM_DECL_MAX_LEN or not _PARAM_DECL_SHAPE.fullmatch(s):
            continue
        # Remove type qualifiers, keep only the symbol name
        parts = s.split()
        if not parts:
            continue
        candidate = parts[-1].strip("*&;,")
        candidate = re.sub(r"\[.*?\]$", "", candidate)
        if candidate and re.match(r"[A-Za-z_]", candidate):
            candidate = _vc_pointer_notation(candidate)
            if candidate not in names:
                names.append(candidate)
    return names


# 배열 원소 확장.
#
# 정본 SUTS 는 배열을 **원소 단위로** 적는다(실측 KJPDS02_PV):
#   입력 엔트리 6,014 중 `name[N]` 3,023(50.3%) · 기대 5,389 중 2,716(50.4%)
#   base 134 중 **120개가 모든 unit 에서 같은 개수** = 관찰 첨자가 아니라 선언 크기
#   최대 원소 60 · 입력 unit당 최대 **96 = 열 상한 정확히**(초과 0) · 기대 84 = 상한
#
# ⚠ 상한을 넘기면 **펼치지 않고 base 이름을 그대로 둔다**. 원소를 잘라 넣으면
#   "이 배열은 앞 k칸만 시험한다"는 없는 사실을 적게 되고, 뒤에 오는 **다른 변수**가
#   통째로 밀려난다. 변수는 하나도 잃지 않고 입도만 낮추는 쪽이 정직하다.
#   건너뛴 것은 `array_expansion` 으로 보고한다 — 침묵시키지 않는다.
# 다차원은 `9x8` 로 실린다 — 차원을 곱해 버리면 `[i][j]` 를 복원할 수 없다.
_SIZE_TAIL_RE = re.compile(r"\(\s*size\s*:\s*(\d+(?:\s*x\s*\d+)*)\s*\)", re.I)
# 파라미터 표시엔 선언 차원이 `buf[10]`·`t[3][4]` 로 이미 들어 있다(`_format_param_entry`).
# 이 필드에서 `[N]` 은 **항상 선언 크기**다(원소 표기를 내는 생산자가 없다).
_PARAM_DIM_RE = re.compile(r"((?:\[\d+\])+)\s*$")

# 본문에서 **관찰된** 첨자(`_scan_name_usage` → `_format_param_entry` 의 `(idx: …)`).
# 선언 크기가 없는 **포인터 버퍼**의 유일한 폭 신호다 — 포인터는 원소 수가 선언에
# 없고 호출자만 안다(`U8 *pu8t_ResponseBuffer`).
#
# ⚠ R10 이 관찰 첨자를 기각한 건 **선언 크기가 있는 배열**에서다(일치 146 → 10 폭락).
#   그래서 아래 소비처는 `(size:)` 로 차원을 얻지 못했을 때**만** 이걸 본다. 두 신호가
#   경합하면 선언이 이긴다 — 관찰은 본문에 등장한 첨자뿐이라 배열보다 좁다.
_OBS_IDX_TAIL_RE = re.compile(r"\(\s*idx\s*:\s*([^)]*)\)", re.I)
_OBS_IDX_LITERAL_RE = re.compile(r"^\d+[uUlL]*$")


# 타입 문자열의 한정자. `const st_s_DTC` 처럼 붙어 오면 struct 정의를 못 찾는다.
# ⚠ 단어 경계 필수 — 없으면 `constant_t` 의 `const` 까지 지워 타입 이름이 깨진다.
_CV_QUALIFIER_RE = re.compile(r"\b(?:const|volatile|static)\b")


def _dim_product(dims: Tuple[int, ...]) -> int:
    n = 1
    for d in dims:
        n *= int(d)
    return n


@lru_cache(maxsize=4096)
def _decl_dims_from_array_field(text: str) -> Tuple[int, ...]:
    r"""`globals_info_map` 의 `array` 문자열(`'[5][7][7]'`)을 차원 튜플로.

    ⚠ `re.findall(r"\d+")` 로 뽑으면 `[DATA_LEN2]` 같은 **매크로 이름 속 숫자**를
      주워 없는 크기를 지어낸다. 대괄호 개수와 숫자 차원 개수가 **정확히 일치**할
      때만 인정하고, 하나라도 비숫자면 전부 버린다(`[SIGNATURE_SIZE]` → `()`).
    """
    t = str(text or "").strip()
    if not t:
        return ()
    nums = re.findall(r"\[(\d+)\]", t)
    if not nums or len(nums) != t.count("["):
        return ()
    return tuple(int(n) for n in nums)


def _struct_member_dims(
    name: str,
    globals_info: Dict[str, Dict[str, str]],
    struct_members: Dict[str, Dict[str, str]],
) -> Tuple[int, ...]:
    """`s_LinFrame.LIN_data` → `(8,)`. 구조체 **정의**에서 멤버 배열 차원을 찾는다.

    root 의 타입을 `globals_info` 에서 얻어 `struct_members[타입][멤버경로]` 를 본다.
    ⚠ 포인터 파라미터(`ctx`·`pst_Queue`)는 root 타입을 모르므로 여기서 안 걸린다 —
      의도적이다. 파라미터 타입까지 열면 실측상 일치 +34 에 과다 +176 이었다
      (`SHA256_CTX.buffer[64]` 를 통째로 펼쳐서). 정본이 지지하지 않는다.
    """
    # ⚠ `ctx[0].state` 처럼 root 에 첨자가 붙은 포인터 표기는 여기서 **자동으로**
    #   걸러진다 — `globals_info` 키는 맨 이름(`ctx`)이라 `ctx[0]` 조회가 실패한다.
    #   `"[" in root` 가드를 따로 두면 같은 것을 두 번 막아 뮤테이션이 살아남는다.
    root, _, rest = str(name or "").partition(".")
    if not rest:
        return ()
    ty = _CV_QUALIFIER_RE.sub("", str((globals_info.get(root) or {}).get("type") or "")).strip()
    if not ty:
        return ()
    return _decl_dims_from_array_field(str((struct_members.get(ty) or {}).get(rest) or ""))


def _declared_type_map(globals_info: Optional[Dict[str, Dict[str, str]]]) -> Dict[str, str]:
    """전역 선언의 `이름 → 타입`. unit 마다 안 바뀌므로 **루프 밖에서 한 번** 만든다."""
    return {
        str(_gn): _ty
        for _gn, _gi in (globals_info or {}).items()
        if (_ty := _CV_QUALIFIER_RE.sub("", str((_gi or {}).get("type") or "")).strip())
    }


def _root_type_hints(
    *raw_groups: List[str],
    declared_types: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """root 이름 → 구조체 **타입 이름**.

    원시 엔트리는 타입을 앞에 달고 온다(`[INOUT] ST_SAFE_WRITE_QUEUE* pst_Queue->ast_Queue`).
    파라미터는 전역 선언에 없으므로 이 접두가 **유일한** 타입 출처다.
    ⚠ 프로토타입을 소스에서 다시 파싱하지 않는다 — 같은 판정을 두 벌 두면 한쪽만
      고쳐지는 실패를 이 저장소가 반복해 겪었다. 타입은 이미 엔트리 안에 있다.
    ⚠ 전역 **선언**이 이긴다. 엔트리 접두는 호출 지점 표기라, 어긋나면 선언이 옳다.
    """
    hints: Dict[str, str] = {}
    for group in raw_groups:
        for raw in group or []:
            s = _DIR_TAG_PAT.sub("", str(raw or "").strip(), count=1).strip()
            s = _strip_param_annotations(s)
            # `return U8` 은 선언이 아니라 반환 슬롯이다. 그냥 두면 `{"U8": "return"}`
            # 이라는 뒤집힌 항목이 생긴다 — 지금은 무해하지만 이름이 곧 root 키다.
            if _RETURN_SLOT_RE.match(s):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            # 마지막 토큰이 이름, 그 앞이 타입. `p->m` · `p[0].m` 은 root 만 취한다.
            root = re.split(r"->|\.", parts[-1].strip("*&;,"), maxsplit=1)[0]
            root = re.sub(r"(?:\[[^\]]*\])+$", "", root)
            ty = _CV_QUALIFIER_RE.sub("", " ".join(parts[:-1])).replace("*", " ").strip()
            ty = ty.split()[-1] if ty.split() else ""
            if root and ty and root not in hints:
                hints[root] = ty
    hints.update(declared_types or {})
    return hints


def _mid_member_sizes(
    names: List[str],
    root_types: Dict[str, str],
    struct_members: Dict[str, Dict[str, str]],
) -> Dict[str, Tuple[int, Tuple[int, ...]]]:
    r"""`A.B.C` 에서 **중간** 마디가 선언 배열이면 `{이름: (마디 인덱스, 차원)}`.

    ## 왜 꼬리(`sizes`)와 따로 필요한가 — 이 이름들은 **C 로 성립하지 않는다**

    `pst_Queue[0].ast_Queue.u16_Addr1` 의 `ast_Queue` 는
    `ST_SAFE_WRITE_QUEUE_ENTRY ast_Queue[16]` 이다. **배열에 `.멤버` 는 못 붙인다.**
    첨자를 잃은 경로는 SwUDS 이름 대체에서 온다 — 문서는 `ast_Queue[x]`(자리표시자)
    · `ast_Queue[16]`(선언 크기)로 적는데 `uds_unit_io.clean_param_name` 이 첨자를
    **의도적으로** 전부 뗀다(문서 숫자를 믿으면 없는 원소를 만든다: UDS `CSL[9]` vs
    소스 `U8 CSL[8]`). 그 규칙은 옳다 — 다만 **되붙일 자리**가 꼬리와 root 뿐이라
    중간 마디가 갈 곳이 없었다. 크기는 여기서도 **소스에서만** 얻는다.

    ⚠ 파라미터 타입을 **꼬리**에 쓰지 않는다. 11차 실측이 일치 +34 에 과다 +176
      이었다(`SHA256_CTX.buffer[64]` 통째 확장). 꼬리는 안 펼쳐도 이름이 성립하니
      그건 취향이지만, 중간 마디는 안 붙이면 **틀린 이름**이라 성격이 다르다.
    """
    out: Dict[str, Tuple[int, Tuple[int, ...]]] = {}
    for nm in names:
        # ⚠ `len(parts) < 3` 조기 탈출을 두지 않는다 — 아래 `range(1, len(parts) - 1)`
        #   이 이미 빈 범위가 되어 같은 것을 두 번 막는다. 겹친 가드는 방어가 아니라
        #   뮤테이션이 통째로 사는 사각이다(11차에서 같은 판단으로 두 개를 뺐다).
        parts = str(nm or "").split(".")
        root = re.sub(r"(?:\[[^\]]*\])+$", "", parts[0])
        members = struct_members.get(root_types.get(root) or "") or {}
        if not members:
            continue
        # 마지막 마디는 제외한다 — 그건 `sizes` 가 이미 맡는다.
        for k in range(1, len(parts) - 1):
            if "[" in parts[k]:
                break
            path = ".".join(p.split("[")[0] for p in parts[1:k + 1])
            dims = _decl_dims_from_array_field(str(members.get(path) or ""))
            if dims and _dim_product(dims) > 1:
                out[nm] = (k, dims)
                break
    return out


def _array_sizes(
    *raw_groups: List[str],
    globals_info: Optional[Dict[str, Dict[str, str]]] = None,
    struct_members: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Tuple[int, ...]]:
    """원시 엔트리에서 `이름 → 차원 튜플` 을 모은다(1차원도 `(60,)` 로 담는다).

    `globals_info` 는 **폴백 전용**이다 — unit 지역 엔트리의 `(size: N)` 이 우선한다.
    `struct_members` 는 `타입 → {멤버경로: "[8]"}` 로, 점 있는 이름의 꼬리 확장에 쓴다.
    """
    sizes: Dict[str, Tuple[int, ...]] = {}
    for group in raw_groups:
        for raw in group or []:
            s = str(raw or "")
            dims: Tuple[int, ...] = ()
            m = _SIZE_TAIL_RE.search(s)
            if m:
                dims = tuple(int(x) for x in re.findall(r"\d+", m.group(1)))
            if not dims:
                head = _strip_param_annotations(
                    re.sub(r"^\[(?:IN|OUT|INOUT|INDIRECT2|INDIRECT)\]\s*", "", s.strip())
                )
                m2 = _PARAM_DIM_RE.search(head)
                if m2:
                    dims = tuple(int(x) for x in re.findall(r"\d+", m2.group(1)))
            if not dims or _dim_product(dims) <= 1:
                continue
            name = _clean_global_name(s)
            name = re.sub(r"(?:\[\d+\])+$", "", name)
            if name and _dim_product(dims) > _dim_product(sizes.get(name) or ()):
                sizes[name] = dims
    # ⚠ 7차 라운드에서 입출력 **이름**을 SwUDS 문서로 대체하면서 사각이 생겼다:
    #   문서 유래 이름은 대응하는 소스 엔트리가 없어 `(size: N)` 꼬리도 없다. 선언
    #   크기는 `globals_info_map` 에 이미 있는데 여기서 한 번도 안 봤다 —
    #   `u8s_DataBuffer[60]` 이 `s_UDS_RDBI_RealTimeMonitor` 에서 base 한 칸으로
    #   나가 정본 60칸과 어긋났다(실측: 입력 일치 +60 · 과다 -1 · 사라진 맞춤 0).
    for _gname, _ginfo in (globals_info or {}).items():
        _key = str(_gname or "")
        if not _key or _key in sizes:
            continue
        _gdims = _decl_dims_from_array_field(str((_ginfo or {}).get("array") or ""))
        if _gdims and _dim_product(_gdims) > 1:
            sizes[_key] = _gdims
    # 구조체 멤버 배열 — `DiagData.CloseFailure` 는 전역맵에 **이름 자체가 없다**
    # (전역은 `DiagData` 뿐). 타입을 거쳐 struct 정의에서 차원을 얻는다.
    if struct_members:
        _gi = globals_info or {}
        for _grp in raw_groups:
            for _raw in _grp or []:
                _nm = _clean_global_name(str(_raw or ""))
                if not _nm or "." not in _nm or _nm in sizes:
                    continue
                _mdims = _struct_member_dims(_nm, _gi, struct_members)
                if _mdims and _dim_product(_mdims) > 1:
                    sizes[_nm] = _mdims
    return sizes


def _observed_idx_map(
    raw_groups: List[List[str]],
    want_tags: Set[str],
) -> Dict[str, Tuple[int, ...]]:
    """`이름 → 본문에서 관찰된 리터럴 첨자` — **선언 크기가 없는 포인터 버퍼**용.

    정본 SUTS 는 포인터 버퍼도 원소 단위로 적는다(`pu8t_ResponseBuffer[0..39]` 40칸).
    선언에 크기가 없으니 폭을 지어낼 수 없고, 본문이 실제로 만진 첨자만이 근거다.

    **방향 태그로 열이 갈린다** — 정본 실측(KJPDS02_PV, 손실 0 조합 탐색):

        [IN]  → 읽는 원소를 **입력** 열에      적중 28 · 과다  1
        [OUT] → 쓰는 원소를 **기대** 열에      적중 53 · 과다  0
        둘 다                                  적중 81 · 과다  1 · **사라진 맞춤 0**
        [OUT] 를 양쪽에 (대조군)               적중 63 · 과다 43 · 사라진 맞춤 1

    `[INOUT]` 은 넣지 않는다 — 적중이 **한 칸도 안 늘고**(81 그대로) 정본에 없는
    unit 의 과다만 커진다. `[INDIRECT*]` 도 같은 이유로 제외다.

    ⚠ **첨자가 하나라도 변수식이면 그 슬롯을 통째로 버린다**(`(idx: index)` ·
      `(idx: u32t_HashOffset | 1U)`). 리터럴만 골라 쓰면 폭이 임의로 좁아져
      "이 배열은 이 칸만 시험한다" 는 없는 사실을 적게 된다.
    ⚠ `(size:)` 가 같이 붙은 슬롯도 버린다 — 선언 크기가 이겨야 한다(R10).
    """
    out: Dict[str, Tuple[int, ...]] = {}
    for group in raw_groups:
        for raw in group or []:
            s = str(raw or "")
            m = _OBS_IDX_TAIL_RE.search(s)
            if not m or _SIZE_TAIL_RE.search(s):
                continue
            tag = _DIR_TAG_PAT.match(s)
            if not tag or tag.group(1).upper() not in want_tags:
                continue
            toks = [t.strip() for t in m.group(1).split(",") if t.strip()]
            if not toks or not all(_OBS_IDX_LITERAL_RE.match(t) for t in toks):
                continue
            name = _clean_global_name(s)
            name = re.sub(r"(?:\[\d+\])+$", "", name)
            if not name:
                continue
            idxs = tuple(sorted({int(re.sub(r"[uUlL]+$", "", t)) for t in toks}))
            if len(idxs) <= 1:
                # 첨자가 하나면 `x` → `x[0]` 로 **표기만** 바뀌고 폭은 그대로다.
                # ⚠ 그 표기 변경은 R22 에서 전수 측정해 **기각**했다: 정본은 base
                #   표기를 압도적으로 쓴다(우리가 base 로 낸 쌍 중 정본도 base =
                #   입력 2,600/3,489 · 기대 2,295/2,635). `[0]` 을 붙이면 **4,895칸**
                #   을 잃고, 손실 0 인 판별 규칙이 없다(`(idx:)` 로 좁혀도 손실 1~8).
                continue
            # 같은 이름이 여러 슬롯에 오면 **넓은 쪽**을 쓴다. 좁은 쪽을 채택하면
            # 정본이 적는 원소를 빠뜨린다(under-specification = under-testing).
            if len(idxs) > len(out.get(name) or ()):
                out[name] = idxs
    return out


def _nonvoid_function_names(function_details: Dict[str, Dict[str, Any]]) -> Set[str]:
    """반환값이 있는 함수 이름 집합.

    unit 마다 안 바뀌므로 **루프 밖에서 한 번** 만든다(`_declared_type_map` 과 같은 자리 —
    13차에 전역 맵을 루프 안에서 만들어 176만 회 헛돈 전례가 있다).

    판정은 파서가 낸 `[OUT] return <타입>` 슬롯으로만 한다. 프로토타입을 다시 파싱하지
    않는다 — 같은 판정을 두 벌 두면 한쪽만 고쳐진다(이 시리즈의 반복 실패다).
    태그 제거와 슬롯 판정은 기존 `_DIR_TAG_PAT` · `_RETURN_SLOT_RE` 를 그대로 쓴다.
    """
    out: Set[str] = set()
    for _d in (function_details or {}).values():
        # ⚠ 엔트리가 dict 가 아닐 수 있다(`{"SwUFn_001": "not_a_dict"}`) — 본 루프는
        #   그걸 이미 견디므로 여기서 크래시하면 **없던 실패를 새로 만드는** 것이다.
        #   `isinstance` 가 None 도 함께 거르므로 `(_d or {})` 를 겹쳐 두지 않는다.
        if not isinstance(_d, dict):
            continue
        nm = str(_d.get("name") or "")
        if not nm:
            continue
        for o in (_d.get("outputs") or []):
            s = _DIR_TAG_PAT.sub("", str(o or "").strip(), count=1).strip()
            if _RETURN_SLOT_RE.match(s):
                out.add(nm)
                break
    return out


def _out_param_names_by_function(
    function_details: Dict[str, Dict[str, Any]],
) -> Dict[str, List[str]]:
    """함수 이름 → 그 함수의 `[OUT]` **파라미터** 이름들(반환값은 뺀다).

    `_nonvoid_function_names` 와 같은 자리에서 **한 번만** 만든다(unit 마다 안 바뀐다).

    ⚠ **`outputs` 키도 봐야 한다.** R23 측정 첫 판은 `inputs` 만 훑어 표적 22 중 15 를
      "파서가 태깅을 안 한다" 로 오판했다 — `sf_TryAddU32` 의 `sum` 은 `inputs` 이 아니라
      `outputs: [OUT] UINT32 * sum` 에 실려 있었다. 한 분류로 몰리면 데이터가 아니라
      조회 경로부터 의심할 것(이 시리즈에서 네 번째다).

    이름 추출은 `_extract_var_names` 를 그대로 쓴다 — 같은 판정을 두 벌 두면 한쪽만
    고쳐진다(이 시리즈의 반복 실패다).
    """
    out: Dict[str, List[str]] = {}
    for _d in (function_details or {}).values():
        if not isinstance(_d, dict):
            continue
        nm = str(_d.get("name") or "")
        if not nm:
            continue
        acc: List[str] = []
        for key in ("inputs", "outputs"):
            for raw in (_d.get(key) or []):
                m = _DIR_TAG_PAT.match(str(raw or ""))
                if not m or m.group(1).upper() != "OUT":
                    continue
                for got in _extract_var_names([str(raw)]):
                    if got != _RETURN_VAR and got not in acc:
                        acc.append(got)
        if acc:
            out[nm] = acc
    return out


def _stub_out_param_names(
    calls_list: Any,
    nonvoid: Set[str],
    out_params: Dict[str, List[str]],
    own: str = "",
) -> List[str]:
    """stub 된 피호출이 **출력 파라미터에 써 넣는 값** — 정본의 시험 **입력**이다.

    `_stub_return_names` 와 같은 계열이다. VectorCAST 가 피호출을 stub 하면 반환값뿐
    아니라 포인터 출력 파라미터도 주입해야 하므로, 정본 Inpt 열에
    `EEPROM_GetByte() Data[0]` · `sf_TryAddU32() sum[0]` 이 실린다.

    실측(KJPDS02_PV, 2026-08-19 · R23):
        정본 표적  입력 22칸 · 기대 10칸
        후보 규칙                     생산   적중   과다   정밀도
          조건 없음([OUT] 전부)        154     12    142     7.8%
          **비-void 피호출만**          35     12     23    34.3%   ← 채택
          out-param 1개뿐               43      9     34    20.9%
          비-void ∧ 1개뿐               28      9     19    32.1%

    **비-void 조인이 같은 적중 12 를 과다 142→23 으로 낸다.** 우리가 이미
    `X() return` 을 내는 대상과 정확히 겹치는 집합이라 근거도 같다 — stub 되는
    함수만 그 출력 파라미터를 주입받는다.

    ⚠ **접미 `[0]` 은 R22 를 뒤집는 게 아니다.** R22 가 기각한 건 *배열 변수*에
      `[0]` 을 붙이는 것이고(정본의 지배 표기가 base 라 4,895칸 손실), 여기 피호출
      출력 파라미터는 정본이 **일관되게 `[0]`** 으로 적는다. 두 표기를 다 재봤다:
      `[0]` 적중 12 · 접미 없음 적중 **0**. 이름족이 다르면 표기도 다르다.

    ⚠ **입력 열 전용이다.** 기대 열 표적 10칸은 적중 0 이었다 — 8칸이 2단 중첩 표기
      (`s_sha256_accumulate_state() pt_WorkState[0]() u32t_A`)고 2칸은 피호출이 아니라
      레지스터 매크로(`_PTT() Byte`)다. 낼 수 없는 걸 내는 척하지 않는다.
    """
    seen: Set[str] = set()
    out: List[str] = []
    for c in (calls_list or []):
        nm = str(c or "").strip()
        # 비-void 판정이 곧 "stub 대상" 판정이다. `nm and` 를 겹쳐 두지 않는다 —
        # 빈 이름은 `nonvoid` 에 애초에 안 들어간다(`_stub_return_names` 와 같은 이유).
        if nm not in nonvoid or nm == own:   # 재귀 호출은 stub 대상이 아니다(R14 리뷰 r2 B-I1)
            continue
        for p in (out_params.get(nm) or ()):
            cell = f"{nm}() {p}[0]"
            if cell not in seen:
                seen.add(cell)
                out.append(cell)
    return out


def _stub_return_names(calls_list: Any, nonvoid: Set[str], own: str = "") -> List[str]:
    """이 unit 이 호출하는 **비-void** 함수의 반환값 — 정본의 시험 **입력**이다.

    VectorCAST 는 피호출 함수를 stub 하고 그 반환값을 주입하므로, 정본 Inpt 열에
    `u16g_Conv_AngleToPulse() return` 이 실린다. 우리는 이걸 한 번도 안 냈다(0칸).

    실측(KJPDS02_PV, 2026-08-19):
        정본 입력 stub 칸 198 · 136 unit · 피호출 함수 **100% 가 비-void**
        후보 규칙       일치   채운행 과다   정밀도
          calls_list    189       253        42.8%   ← 채택
          called         81       156        34.2%
          calling(역방향)  0       230         0.0%
          logic 등장분만 178       250        41.6%   ← 필터가 오히려 나쁘다
          파일 경계     채택 79.9% vs 미채택 69.9% — 방향이 반대라 신호 아님

    ⚠ **정본이 어느 callee 를 stub 하는지 가르는 정적 신호는 없다**(위 4개 전부 실패).
      다음 라운드가 같은 데를 다시 파지 않도록 숫자를 남긴다. 그럼에도 채택한 이유는
      4차(맨이름)·12차(통짜 표기) 기각과 성격이 다르기 때문이다 — 저 둘은 **순손실**과
      **근거 부족**이었고, 여기는 사라진 맞춤 0 에 순증 +189 다. 과다 253 도 지어낸
      이름이 아니라 **실제로 호출하는 비-void 함수**라 stub 가능한 실재 대상이다.

    ⚠ **입력 열 전용이다.** 정본 기대 열의 stub return 은 **0칸**이다.
    """
    seen: Set[str] = set()
    out: List[str] = []
    for c in (calls_list or []):
        nm = str(c or "").strip()
        # `nm and` 를 앞에 두지 않는다 — 빈 이름은 `nonvoid` 에 애초에 안 들어간다
        # (`_nonvoid_function_names` 가 거른다). 겹쳐 막으면 뮤테이션이 통째로 산다.
        # (R14 review W1) 재귀 호출은 stub 대상이 아니다 — 시험 대상 함수는 자기 시험에서 실제로 돈다.
        if nm in nonvoid and nm not in seen and nm != own:
            seen.add(nm)
            out.append(f"{nm}() {_RETURN_VAR}")
    return out


def _elem_suffixes(dims: Tuple[int, ...]) -> List[str]:
    """`(9, 8)` → `['[0][0]', '[0][1]', …]` — 정본과 같은 row-major 순서."""
    out = [""]
    for d in dims:
        out = [f"{pre}[{i}]" for pre in out for i in range(int(d))]
    return out


def _expand_array_entries(
    names: List[str],
    sizes: Dict[str, Tuple[int, ...]],
    budget: int,
    root_sizes: Optional[Dict[str, Tuple[int, ...]]] = None,
    mid_sizes: Optional[Dict[str, Tuple[int, Tuple[int, ...]]]] = None,
    parallel: Optional[List[str]] = None,
    observed_idx: Optional[Dict[str, Tuple[int, ...]]] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """배열 이름을 원소로 펼친다. 예산이 모자라면 **펼치지 않고 그대로 둔다**.

    첨자가 붙는 자리는 셋이고, 전부 "몇 번째 마디 뒤에 붙나"의 다른 값이다:
      · `mid_sizes`  — **중간** 마디(`X.arr.m` → `X.arr[0].m`). 아래 순서 주의.
      · `sizes`      — 이름 **꼬리**(`u8s_Buf` → `u8s_Buf[0]`, `PS.Data` → `PS.Data[0]`)
      · `root_sizes` — 점 있는 이름의 **root 뒤**(`g_Ph.u8_Max` → `g_Ph[0].u8_Max`).
        구조체 **배열**의 멤버라 정본이 첨자를 root 에 붙인다. 꼬리에 붙이면
        `g_Ph.u8_Max[0]` 이라는 **없는 대상**이 된다.

    ⚠ **중간이 꼬리보다 먼저다.** 한 이름에서 둘 다 배열이면(이 프로젝트엔 0건),
      꼬리만 펼친 `A.B.C[0]` 은 `A.B` 가 배열이라 **여전히 불성립**이지만, 중간만
      펼친 `A.B[0].C` 는 C 를 통째 배열로 읽는 **성립하는** 이름이다. 덜 틀린 쪽을
      고른다.

    `parallel` 은 `names` 와 **같은 길이**인 부속 리스트다(예: 태그 붙은 원문).
    주면 같은 배수로 함께 펼쳐 `stats["parallel"]` 로 돌려준다 — 원소는 base 의
    값을 그대로 복제한다(한 배열의 원소는 타입도 경계값도 같다).
    ⚠ 이름을 **인덱스로** 원문과 짝짓는 소비처가 있으면 이걸 안 쓰는 순간 짝이
      조용히 어긋난다 — 잘못된 값이 나오는 게 아니라 **다른 변수의** 값이 붙는다.
      SITS 가 그렇다(`expected_raws[ev_idx]`). SUTS 는 이름 기반 추론이라 안 쓴다.
    """
    par_in = list(parallel) if parallel is not None else None
    if par_in is not None and len(par_in) != len(names):
        # 길이가 다르면 짝이 이미 깨진 것이다. 조용히 잘라 맞추면 그 사실이 사라진다.
        raise ValueError(
            f"parallel 길이 불일치: names={len(names)} parallel={len(par_in)}")
    par_out: List[str] = []
    out: List[str] = []
    expanded: List[str] = []
    observed: List[str] = []
    skipped: List[Dict[str, Any]] = []
    total = len(names)
    for pos, nm in enumerate(names):
        at_node = -1
        dims: Tuple[int, ...] = ()
        _mid = (mid_sizes or {}).get(nm)
        if _mid:
            at_node, dims = _mid
        if not dims:
            dims = sizes.get(nm) or ()
        if not dims and root_sizes and "." in nm:
            # 첨자가 이미 붙은 root(`ctx[0]`)는 키가 안 맞아 조회가 실패한다 —
            # 별도 가드를 두면 겹쳐서 막게 되고, 그건 방어가 아니라 사각이다.
            dims = root_sizes.get(nm.split(".", 1)[0]) or ()
            if dims:
                at_node = 0
        if dims:
            sfxs = _elem_suffixes(dims)
        else:
            # 선언 크기를 **어느 경로로도** 못 얻은 이름에만 관찰 첨자를 쓴다.
            # 순서가 곧 정책이다 — 위에서 dims 가 잡히면 여기 오지 않는다(R10).
            #
            # ⚠ `at_node = -1` 을 여기 두지 않는다. 위 두 경로(`_mid_member_sizes` ·
            #   `root_sizes`)는 **dims 가 있을 때만** at_node 를 세우므로 여기 도달한
            #   시점에 at_node 는 이미 -1 이다. 겹쳐 막으면 방어가 아니라 뮤테이션이
            #   통째로 사는 사각이 된다(이 파일이 같은 판단으로 이미 두 개를 뺐다).
            _obs = (observed_idx or {}).get(nm) or ()
            sfxs = [f"[{i}]" for i in _obs]
        n = len(sfxs)
        if n <= 1:
            out.append(nm)
            if par_in is not None:
                par_out.append(par_in[pos])
            continue
        remaining = budget - len(out)
        # 남은 이름들도 최소 한 칸씩은 자리가 있어야 한다.
        # ⚠ `names.index(nm)` 는 같은 이름이 두 번 들어오면 **첫 위치**를 돌려줘
        #   예약분을 과다 계산한다 — 위치는 열거로 받는다.
        reserve = total - pos - 1
        if n > remaining - reserve:
            out.append(nm)
            if par_in is not None:
                par_out.append(par_in[pos])
            skipped.append({"name": nm, "elements": n, "remaining": max(0, remaining - reserve)})
            continue
        if at_node >= 0:
            # 마디 `at_node` **뒤에** 첨자를 넣는다. root 는 `at_node == 0` 인 특수형일
            # 뿐이라 삽입 로직을 따로 두지 않는다(같은 일을 두 벌 두면 한쪽만 고쳐진다).
            _parts = nm.split(".")
            _head = ".".join(_parts[: at_node + 1])
            _tail = ".".join(_parts[at_node + 1:])
            out.extend(f"{_head}{sfx}.{_tail}" for sfx in sfxs)
        else:
            out.extend(nm + sfx for sfx in sfxs)
        if par_in is not None:
            par_out.extend([par_in[pos]] * n)
        expanded.append(nm)
        if not dims:
            # 선언이 아니라 **관찰**로 폭을 정한 것 — 근거가 약한 쪽이므로 분리해
            # 보고한다. 합쳐 세면 "선언 크기로 펼쳤다" 로 읽혀 근거가 부풀려진다.
            observed.append(nm)
    return out, {
        "expanded": expanded,
        "observed": observed,
        "skipped": skipped,
        "budget": budget,
        "used": len(out),
        # 부속 리스트를 함께 펼친 결과(`parallel` 을 준 경우에만). 길이는 항상 out 과 같다.
        "parallel": par_out if par_in is not None else None,
    }


def _clean_global_name(g: str) -> str:
    # 태그 제거는 `_DIR_TAG_PAT` **단일 출처**로 한다. 여기 목록을 따로 들고 있다가
    # `[INDIRECT2]` 를 빼먹었었다 — 마지막 토큰을 취하는 아래 로직 덕에 우연히 살아
    # 있었을 뿐, 태그가 하나 늘 때 한쪽만 고쳐지는 그 실패를 이 저장소가 두 번 겪었다.
    s = _DIR_TAG_PAT.sub("", str(g).strip(), count=1).strip()
    s = _strip_param_annotations(s)
    parts = s.split()
    return parts[-1].strip("*&;,") if parts else ""


# ---------------------------------------------------------------------------
# Phase 2: Variable type analysis
# ---------------------------------------------------------------------------

_globals_type_cache: Dict[str, str] = {}


def _gim_to_type_map(gim: Dict[str, Any]) -> Dict[str, str]:
    """globals_info_map({var:{type:...}})에서 {var: raw_type} 타입맵을 추출한다.

    ``set_globals_type_cache``(프로세스 전역 시딩)와 ``_build_doc_proposal``(로컬 type_cache
    주입, workflow/impact_orchestrator.py)의 **단일 출처**다 — 두 곳이 독립 구현이면 한쪽만
    고쳐 드리프트하는 전례가 있어 통합한다(비-dict/빈 타입 값 방어 포함).
    """
    out: Dict[str, str] = {}
    for var_name, info in (gim or {}).items():
        if not isinstance(info, dict):
            continue
        vtype = _prefer_known_decl(info.get("type"), info.get("base_type"))
        if vtype:
            out[str(var_name)] = vtype
    return out


def _gim_typedef_resolved(gim: Dict[str, Any]) -> set:
    """`_gim_to_type_map` 이 **풀린 원 선언(`base_type`)을 고른** 변수 이름들(R76 N94).

    타입맵은 문자열만 실어 "선언이 그대로 아는 타입" 과 "typedef 를 풀어서 안 타입" 이 같은 모양이다. 영향도 초안은
    타입의 근거를 라벨로 보이므로(`globals_map`) 그 둘을 가를 수 있어야 한다 — 별칭 해상은 소스 단계의 추론 한 단계다.
    판정은 `_prefer_known_decl` 과 같은 식을 쓴다(선언이 모르는 타입이고 풀린 값이 있을 때).
    """
    out: set = set()
    for var_name, info in (gim or {}).items():
        if not isinstance(info, dict):
            continue
        decl = str(info.get("type") or "").strip()
        base = str(info.get("base_type") or "").strip()
        if base and _prefer_known_decl(decl, base) == base and base != decl:
            out.add(str(var_name))
    return out


def _prefer_known_decl(decl: Any, base: Any) -> str:
    """선언이 이미 아는 타입이면 **선언**, 모르는 타입일 때만 소스 단계가 typedef 를 풀어 둔 원 선언(`base_type`).

    (R73 N92) 순서가 중요하다 — `U16` 은 표가 아는 이름인데 이 프로젝트에선 `typedef unsigned int U16` 이라, 풀린 쪽을
    먼저 보면 폭을 모르는 `unsigned int` 가 되어 아는 타입 1,647칸이 도로 `unknown` 이 된다(첫 실측).
    """
    d = str(decl or "").strip()
    b = str(base or "").strip()
    if d and _normalize_type(d) not in ("", _UNKNOWN_TYPE):
        return d
    return b or d


def set_globals_type_cache(gim: Dict[str, Dict[str, str]]) -> None:
    """Populate type cache from globals_info_map for precise type resolution."""
    _globals_type_cache.clear()
    _globals_type_cache.update(_gim_to_type_map(gim))


def infer_variable_type(var_name: str, type_cache: Optional[Dict[str, str]] = None) -> str:
    """Infer C type from variable naming convention or globals_info_map.

    type_cache: 명시적 {var: raw_type} 맵. 주어지면 프로세스 전역 ``_globals_type_cache``
      대신 이것을 읽는다 — 호출자(예: 영향도 문서 초안 합성)가 전역을 변이시키지 않고
      정확한 타입 해상도를 얻게 해 write-race/타 프로젝트 오염을 원천 차단한다.
      None이면 기존대로 전역 캐시를 읽는다(실 문서생성 경로는 무변경).
    """
    cache = type_cache if type_cache is not None else _globals_type_cache
    if var_name in cache:
        raw = cache[var_name]
        mapped = _normalize_type(raw)
        # (R71 N77) `unknown` 도 답이다 — 선언은 있는데 우리가 모르는 타입(구조체·enum·`void *`·typedef)이면
        #   이름 패턴·기본값으로 내려가지 않는다. 예전엔 `""` 로 떨어져 `void *` 전역 12개가 전부 `uint8_t`
        #   (0/127/255)가 됐다. 멤버 경로(`s.Word`)는 캐시 키가 아니라 여기 안 오고 이름 패턴이 그대로 맡는다.
        if mapped:
            return mapped
    return type_from_name_pattern(var_name) or "uint8_t"


def type_from_name_pattern(var_name: str) -> str:
    """이름 규칙(헝가리안 `u16g_`·`_Flag`·`bool` …)만으로 얻는 타입 키. 없으면 `""` — 기본값을 주지 않는다.

    (R72 리뷰 W1) `infer_variable_type` 은 끝에 `uint8_t` 를 지어내므로 "이름이 말한 것" 과 "모른다" 를 구분할 수 없다.
    선언이 없는 입력에서 경계값을 만들지 말지 정하는 호출자(STS `_generate_simple_steps`)는 이걸 쓴다.
    """
    for pat, typename in _TYPE_NAME_PATTERNS:
        if pat.search(var_name):
            return typename
    return ""


# (R71 N77) 선언이 있는데 경계값을 아는 스칼라가 아닌 타입. `get_boundary_values` 가 **빈 dict** 를 준다 —
#   값을 지어내지 않는다(예전엔 `_DEFAULT_BOUNDARY` = uint8 로 접혀 구조체 포인터 `pt_Entry` 에 0/127/255 가 섰다).
_UNKNOWN_TYPE = "unknown"
# 폭이 **정의로 정해지는** 이름만 표에 둔다. `int`/`unsigned`/`long`/`char`/`double` 은 타깃(S12Z 계열은 int 16비트)에
# 따라 폭·부호가 갈리므로 여기 없다 → `unknown`(리뷰 W1·W2). `short` 는 사실상 전 임베디드 타깃에서 16비트라 둔다.
_TYPE_ALIASES: Dict[str, str] = {
    "u8": "uint8_t", "u16": "uint16_t", "u32": "uint32_t", "s8": "int8_t", "s16": "int16_t", "s32": "int32_t",
    "int8": "int8_t", "int32": "int32_t", "uint32": "uint32_t", "sint8": "int8_t", "sint16": "int16_t", "sint32": "int32_t",
    "l_u8": "uint8_t", "l_u16": "uint16_t", "l_u32": "uint32_t", "l_bool": "bool", "l_s8": "int8_t", "l_s16": "int16_t",
    "byte": "uint8_t", "word": "uint16_t", "dword": "uint32_t", "boolean": "bool", "_bool": "bool",
    "unsigned char": "uint8_t", "signed char": "int8_t", "unsigned short": "uint16_t", "short": "int16_t",
    "unsigned short int": "uint16_t", "short int": "int16_t",
}
_TYPE_DECORATION_RE = re.compile(r"\[[^\]]*\]|[*&()]|\b__?(?:far|near|huge|interrupt)\b")


def _normalize_type(raw: str) -> str:
    """선언 문자열 → 경계값 표의 타입 키. 없으면 `""`(선언 없음) 또는 `"unknown"`(선언은 있는데 모르는 타입).

    (R71 N77) 포인터·배열은 **가리키는/원소 타입**으로 읽는다(정본 VectorCAST 가 포인터를 1원소 이상의 배열로
    잡는 것과 같은 뜻) — `U16 *Values` 는 uint16 이지 uint8 이 아니다. `const`/`volatile`/`__far` 는 걷어낸다.
    `void *`·구조체·enum·모르는 typedef 는 `unknown` — 이름 패턴이나 기본값으로 값을 지어내지 않는다.
    ⚠ 부분문자열로 맞추지 않는다(리뷰 C1): `struct ST_Bits`·`T_InhibitTime`·`Bitmask_t` 가 `bit` 에, `PointerType` 이
      `int` 에 걸려 구조체에 0/1 경계가 섰다. 정규화한 문자열 **전체** 또는 **마지막 토큰**이 표의 이름과 같을 때만이다
      (`struct X`·`enum Y` 는 그 규칙만으로 `unknown` 이 된다 — 별도 단락은 등가 변이라 두지 않는다).
    """
    r = str(raw or "").strip()
    if not r:
        return ""
    r = _CV_QUALIFIER_RE.sub(" ", r)
    r = _TYPE_DECORATION_RE.sub(" ", r)
    r = " ".join(r.lower().split())
    if not r:
        return ""
    for cand in (r, r.split()[-1]):
        if cand in _TYPE_BOUNDARIES:
            return cand
        if cand in _TYPE_ALIASES:
            return _TYPE_ALIASES[cand]
    return _UNKNOWN_TYPE


def get_boundary_values(typename: str) -> Dict[str, Any]:
    """타입 키 → 경계값 dict. `unknown`(선언은 있으나 모르는 타입)은 **빈 dict** — 값이 없다는 사실이 답이다."""
    if typename in (_UNKNOWN_TYPE, _ENUM_TYPE, _RANGE_TYPE):
        # `enum` 의 경계는 값 집합(`enum_bounds`)에서만 온다 — 여기로 오면 uint8 기본값으로 접혀 선언 도메인 밖 값이
        # 선다(리뷰 C1: 같은 unit 표에 `BV_MAX=18` 과 `MCDC_BASE=255`).
        return {}
    normalized = typename.lower().replace(" ", "").replace("_t", "_t")
    return _TYPE_BOUNDARIES.get(normalized, _DEFAULT_BOUNDARY)


_ENUM_TYPE = "enum"
# (R74) 소스 선언은 모르는 타입이지만 설계서(SwUDS Value Range)나 HSIS 가 값 범위를 적어 둔 변수.
_RANGE_TYPE = "range"


def enum_bounds(domain: Any) -> Dict[str, Any]:
    """(R73 N92) enum 의 닫힌 값 집합 → 경계값 dict. 최소·최대·가운데 값은 **열거자 값 그대로**, 범위 밖은 ±1.

    소스 단계가 적어 둔 `value_domain`(`{"values": [...]}`)에서만 만든다 — 값 집합을 모르면 빈 dict(지어내지 않는다).
    """
    try:
        vals = sorted({int(v) for v in ((domain or {}).get("values") or [])})
    except (TypeError, ValueError, AttributeError):
        return {}
    if not vals:
        return {}
    return {"min_inv": vals[0] - 1, "min": vals[0], "mid": vals[len(vals) // 2], "max": vals[-1], "max_inv": vals[-1] + 1}


def _unit_value_domains(info: Dict[str, Any], gim: Dict[str, Any], names: List[str]) -> Dict[str, Dict[str, Any]]:
    """unit 변수 이름 → enum 값 집합. 파라미터(`param_value_domains`)가 같은 이름의 전역(`value_domain`)보다 앞선다."""
    out: Dict[str, Dict[str, Any]] = {}
    params = info.get("param_value_domains") or {}
    for v in names:
        dom = params.get(v) or ((gim.get(v) or {}).get("value_domain") if isinstance(gim.get(v), dict) else None)
        if isinstance(dom, dict) and dom.get("values"):
            out[v] = dom
    return out


def _unit_uds_param_info(uds_rec: Optional[Dict[str, Any]], names: List[str]) -> Dict[str, Dict[str, Any]]:
    """unit 변수 이름 → SwUDS 파라미터 표의 `{"type", "range"}`(R74). 원소로 펼친 이름(`buf[3]`)은 첨자를 떼고 찾는다.

    설계서가 직접 적은 타입·범위라 경계값의 **가장 강한 출처**다(KJPDS02 SwUDS v3.03: 파라미터 5,914행 중 범위가 타입 전폭보다
    좁은 `0x00 ~ 0x01` 842행 · `0x00 ~ 0x03` 130행 …). 없으면 싣지 않는다.
    """
    info = (uds_rec or {}).get("param_info") or {}
    if not info:
        return {}
    lowered = {str(k).lower(): v for k, v in info.items()}
    out: Dict[str, Dict[str, Any]] = {}
    for v in names:
        for key in (v, re.sub(r"\[[^\]]*\]", "", v)):
            rec = info.get(key) or lowered.get(key.lower())
            if isinstance(rec, dict) and rec:
                out[v] = rec
                break
    return out


def range_bounds(rng: Any) -> Dict[str, Any]:
    """`[lo, hi]` → 경계값 dict(최소·가운데·최대, 범위 밖 ±1). 정수 두 개가 아니면 빈 dict."""
    try:
        lo, hi = int(rng[0]), int(rng[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return {}
    if lo > hi:
        return {}
    return {"min_inv": lo - 1, "min": lo, "mid": (lo + hi) // 2, "max": hi, "max_inv": hi + 1}


def _param_decl_types(*raw_groups: List[str]) -> Dict[str, str]:
    """파라미터 root 이름 → **선언 타입 문자열**(`U16*`·`const ParamMapEntry_t*`·`bool`).

    (R71 N77) 전역은 `globals_info_map` 에 타입이 있지만 파라미터의 타입 출처는 원시 엔트리의 접두뿐이다
    (`_root_type_hints` 와 같은 자리 — 그쪽은 구조체 **이름** 만 남기려고 포인터 표기와 앞 토큰을 버리므로
    경계값 타입엔 못 쓴다). 한 unit 안에서 파라미터 이름은 같은 이름의 전역보다 앞선다.
    """
    out: Dict[str, str] = {}
    for group in raw_groups:
        for raw in group or []:
            s = _DIR_TAG_PAT.sub("", str(raw or "").strip(), count=1).strip()
            s = _strip_param_annotations(blank_c_comments(s).strip())
            if _RETURN_SLOT_RE.match(s):
                continue
            # 이름 축(`_extract_var_names`)과 **같은 가드** — 주석 블록이 통째로 딸려온 파라미터 문자열을 타입으로
            # 등록하지 않는다(리뷰 W3: `{'macro': 'void) * * This method is …'}`).
            if len(s) > _PARAM_DECL_MAX_LEN or not _PARAM_DECL_SHAPE.fullmatch(s):
                continue
            parts = s.replace("*", " * ").split()
            if len(parts) < 2:
                continue
            name_tok = parts[-1]
            if name_tok == "*":
                continue
            root = re.split(r"->|\.", name_tok.strip("*&;,"), maxsplit=1)[0]
            root = re.sub(r"(?:\[[^\]]*\])+$", "", root)
            ty = " ".join(parts[:-1]).strip()
            if root and ty and root not in out:
                out[root] = ty
    return out


# ---------------------------------------------------------------------------
# Phase 3: Test sequence generation
# ---------------------------------------------------------------------------

def determine_gen_method(unit: Dict[str, Any]) -> str:
    """Determine TC generation method based on function characteristics."""
    logic = unit.get("logic_flow") or []
    has_conditions = any(n.get("type") in ("if", "switch") for n in logic if isinstance(n, dict))
    has_loops = any(n.get("type") == "loop" for n in logic if isinstance(n, dict))
    n_inputs = len(unit.get("input_vars", []))

    if has_conditions and n_inputs > 0:
        return "AEC, ABV"
    if n_inputs > 2:
        return "ABV, AOR"
    if n_inputs > 0:
        return "ABV"
    return "AOR"


# 정본의 `Safety Related` 칸 값 — 구현은 `generators/safety_marks.py` 가 단일 출처다.
# 이 이름은 **유지한다**(외부 호출부·테스트가 여기서 가져간다). 규약·실측 근거는 그쪽
# 모듈 docstring 참조.
resolve_safety_related = _resolve_safety_related


def is_extended_strategy(strategy: Any) -> bool:
    """확장 프로파일에서만 나오는 전략인가 — OAT·경계(BND)·MC/DC 채움 행(R19) 전부, 그리고 기본 자리 수를 넘는
    SWITCH(6+)·GLOBAL(3+)·MCDC(7+)."""
    s = str(strategy or "").strip()
    if s.startswith(("OAT_", BOUNDARY_PREFIX, MCDC_FILL_PREFIX)):
        return True
    for prefix, base_n in (("SWITCH_", _BASE_SWITCH_SLOTS), ("GLOBAL_", _BASE_GLOBAL_SLOTS), ("MCDC_", _BASE_MCDC_SLOTS)):
        if s.startswith(prefix) and s[len(prefix):].isdigit():
            return int(s[len(prefix):]) >= base_n
    return False


def _boundary_domains(unit: Dict[str, Any], input_vars: List[str], var_types: Dict[str, str],
                      var_bounds: Dict[str, Dict[str, Any]], unknown_vars: set) -> Dict[str, Any]:
    """입력마다 움직일 수 있는 정수 도메인 — `(lo, hi)` 범위 또는 enum 열거자 목록(R15 경계 행·R19 MC/DC 채움 행 공용).
    모르는 타입·부동소수·경계 미상은 싣지 않는다(값을 지어내지 않는다)."""
    enum_sets = unit.get("value_domains") or {}
    domains: Dict[str, Any] = {}
    for v in input_vars:
        if v in unknown_vars or var_types.get(v) == "float":
            continue
        if var_types.get(v) == _ENUM_TYPE:
            try:
                vals = sorted({int(x) for x in ((enum_sets.get(v) or {}).get("values") or [])})
            except (TypeError, ValueError, AttributeError):
                vals = []
            # (리뷰 2라운드 W3) 설계서·HSIS 범위가 경계를 정했으면(`bounds_source`) 그 범위 안의 열거자만 — 범위 밖 열거자는
            #   BV_MAX_INV 쪽 값이지 정상 경계가 아니다
            b = var_bounds.get(v) or {}
            if (unit.get("bounds_source") or {}).get(v) in ("uds_range", "hsis_range") and \
                    isinstance(b.get("min"), int) and isinstance(b.get("max"), int):
                vals = [x for x in vals if b["min"] <= x <= b["max"]]
            if len(vals) >= 2:
                domains[v] = vals
            continue
        b = var_bounds.get(v) or {}
        lo, hi = b.get("min"), b.get("max")
        if isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, int) or not isinstance(hi, int) or lo >= hi:
            continue
        domains[v] = (lo, hi)
    return domains


def _append_boundary_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]], input_vars: List[str],
                          output_vars: List[str], var_types: Dict[str, str], var_bounds: Dict[str, Dict[str, Any]],
                          unknown_vars: set) -> None:
    """(R15) 행동 경계 행 — `generators.boundary_rows.find_boundaries` 가 소스 oracle 로 찾은 인접 입력 쌍을 시퀀스 뒤에 붙인다.

    움직일 수 있는 입력은 정수 경계가 정해진 것만(모르는 타입·부동소수·경계 미상 제외 — 값을 지어내지 않는다). enum 은
    **열거자 값 집합**으로 넘긴다 — 열거자 사이의 정수는 쓰지 않는다(리뷰 C2). 기준 행 후보는 전 입력 중간값(BV_MID) → MC/DC
    설계 벡터 → 조건 조합 → 나머지 순으로 넘기고, 후보가 상한보다 많으면 탐색기가 한 번씩 돌려 **서로 다른 출력 상태**·도출
    출력이 많은 행을 먼저 쓴다(이 순서는 동률일 때만). 도메인 밖 값을 가진 행(BV_*_INV)은 기준이 아니다. 기대값은 여기서 적지 않는다: 붙인 뒤
    같은 oracle(`apply_sequence_evidence`)이 모든 행과 똑같이 도출한다. 탐색 요약은 `unit["boundary_search"]` 에 남는다.
    탐색이 실패해도 문서는 만든다 — 그 unit 만 경계 행 없이 두고 사유를 남긴다(리뷰 C1).
    """
    domains = _boundary_domains(unit, input_vars, var_types, var_bounds, unknown_vars)
    outputs = list(dict.fromkeys([*output_vars, *(k for s in sequences for k in (s.get("expected") or {}))]))

    def _rank(s: Dict[str, Any]) -> int:
        name = str(s.get("strategy") or "")
        return 0 if name == "BV_MID" else 1 if name.startswith("MCDC_") else 2 if name.startswith("COND_COMB_") else 3
    order = sorted(sequences, key=_rank)
    # 행이 비운 입력의 채움 값 — BV_MID 와 같은 중간값에서 출발한다(넓은 범위면 입력마다 위치만큼 옮겨 서로 다르게, enum 은 열거자).
    mids = {v: (var_bounds.get(v) or {}).get("mid") for v in domains}
    try:
        found = find_boundaries(
            unit, [{"inputs": s.get("inputs") or {}, "strategy": s.get("strategy")} for s in order], domains, outputs,
            [s.get("inputs") or {} for s in sequences],
            defaults={v: m for v, m in mids.items() if isinstance(m, int) and not isinstance(m, bool)})
    except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
        _logger.warning("SUTS 경계 행 탐색 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        unit["boundary_search"] = {"status": f"error:{type(exc).__name__}", "rows": 0}
        return
    unit["boundary_search"] = found["report"]
    for i, row in enumerate(found["rows"]):
        inputs = {k: _format_test_value(v, var_types.get(k, "uint8_t")) for k, v in row["inputs"].items()}
        side = "경계 아래" if row["side"] == "lo" else "경계 위"
        changed = row["outputs_changed"]
        shown = ", ".join(changed[:3]) + (f" 외 {len(changed) - 3}" if len(changed) > 3 else "")
        filled = row.get("filled") or {}
        fill_note = (" · 기준 행이 비운 입력을 채움: " + ", ".join(f"{k}={v}" for k, v in list(filled.items())[:4])
                     + (f" 외 {len(filled) - 4}" if len(filled) > 4 else "")) if filled else ""
        label = (f"행동 경계({side}): {row['variable']}={row['lo'] if row['side'] == 'lo' else row['hi']} — "
                 f"{row['variable']} {row['lo']}→{row['hi']} 에서 {shown} 가 바뀐다"
                 f"(기준 행 {row['base']}{fill_note}, 소스 oracle 탐색 · 미실행)")
        sequences.append({
            "seq_num": len(sequences) + 1, "inputs": inputs,
            # 관측 자리만 연다 — 값은 뒤의 oracle 이 채운다(바뀐 출력 + 기준 행이 관측하던 출력)
            "expected": {o: f"{VERIFY_PREFIX} boundary" for o in dict.fromkeys([*changed, *outputs])},
            "strategy": f"{BOUNDARY_PREFIX}{i}", "description": label, "tc_profile": TC_PROFILE_EXTENDED,
            "boundary": {k: row[k] for k in ("variable", "side", "lo", "hi", "base", "outputs_changed", "filled")},
        })


# (R19) MC/DC 채움 행 — 설계 벡터는 결정이 읽는 입력만 적어 나머지 칸이 비고, 함수가 그 입력을 읽으면 기대값이 서지 않는다
#   (HDPDM01 확장: `initial_value_not_in_inputs` 공란 1,034칸이 **전부** MC/DC 행 324행). 벡터 행은 그대로 두고(쌍 재검증은 행을
#   벡터 JSON 으로 찾는다) 채운 **동반 행**을 더한다. 쌍의 구성원이 아니다 — MC/DC 주장은 원래 행에만 있다.
MCDC_FILL_PREFIX = "FILLED_MCDC_"


def _append_mcdc_fill_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]], input_vars: List[str],
                           output_vars: List[str], var_types: Dict[str, str], fill: Dict[str, int]) -> None:
    """(R19, 확장 프로파일) MC/DC 설계 벡터 행마다, 벡터가 비운 입력을 경계 행(R15)과 **같은 규칙**(`blank_fill`: 중간값에서
    입력 위치만큼 옮긴 값, enum 은 열거자)으로 채운 행을 하나 더한다. 도메인을 모르는 입력은 여전히 비운다. 같은 입력의 행이
    이미 있으면 더하지 않는다. 기대값은 뒤의 oracle 이 모든 행과 똑같이 도출한다. 요약은 `unit["mcdc_fill"]`.
    `fill` 은 선언 타입·열거자가 있는 입력의 채움 값이다(이름 패턴 타입은 추측이라 채우지 않는다 — 리뷰 R1 W5)."""
    seen = {json.dumps(s.get("inputs") or {}, sort_keys=True, default=str) for s in sequences}
    rows = [s for s in sequences if str(s.get("strategy") or "").startswith("MCDC_")]
    report = {"mcdc_rows": len(rows), "rows_with_blanks": 0, "rows": 0, "not_fillable": 0, "duplicates": 0,
              "pruned": 0}
    for row in rows:
        vector = row.get("inputs") or {}
        blank = [v for v in input_vars if v not in vector]
        if not blank:
            continue
        report["rows_with_blanks"] += 1
        filled = [v for v in blank if v in fill]
        if not filled:
            report["not_fillable"] += 1
            continue
        inputs = {v: vector[v] if v in vector else _format_test_value(fill[v], var_types.get(v, "uint8_t"))
                  for v in input_vars if v in vector or v in fill}
        key = json.dumps(inputs, sort_keys=True, default=str)
        if key in seen:
            report["duplicates"] += 1
            continue
        seen.add(key)
        shown = ", ".join(f"{v}={inputs[v]}" for v in filled[:4]) + (f" 외 {len(filled) - 4}" if len(filled) > 4 else "")
        left = [v for v in blank if v not in fill]
        sequences.append({
            "seq_num": len(sequences) + 1, "inputs": inputs,
            "expected": {o: f"{VERIFY_PREFIX} mcdc_fill" for o in output_vars},
            "strategy": f"{MCDC_FILL_PREFIX}{report['rows']}", "tc_profile": TC_PROFILE_EXTENDED,
            "description": (f"MC/DC 설계 벡터(시퀀스 {row.get('seq_num')})의 결정 무관 입력을 채운 행: {shown}"
                            + (f" · 선언 타입이 없어 비운 입력(이름 패턴 타입은 추측): {', '.join(left[:4])}" if left else "")
                            + " — MC/DC 쌍의 구성원이 아니다(기대값은 소스 oracle 도출 · 미실행)"),
            "mcdc_fill": {"from_sequence": row.get("seq_num"), "filled": {v: inputs[v] for v in filled}},
        })
        report["rows"] += 1
    unit["mcdc_fill"] = report


def _drop_duplicate_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]], extended: bool) -> List[Dict[str, Any]]:
    """(R23) 입력이 같은 TC 의 앞 행과 똑같은 행: 확장 전략 행(OAT_*, 기본 자리를 넘는 SWITCH_/GLOBAL_)이면 빼고 뒤 행 번호를
    다시 매긴다. 정본 규모 카탈로그 행의 중복은 남기고 센다. 기록 `unit["duplicate_rows"]`."""
    seen: set = set()
    kept: List[Dict[str, Any]] = []
    record = {"reference_rows_duplicated": 0, "extended_rows_dropped": 0, "extended_rows_duplicated_kept": 0}
    for seq in sequences:
        key = json.dumps(seq.get("inputs") or {}, sort_keys=True, default=str)
        strategy = str(seq.get("strategy") or "")
        if key in seen:
            droppable = extended and seq.get("tc_profile") == TC_PROFILE_EXTENDED and \
                strategy.startswith(("OAT_", "SWITCH_", "GLOBAL_"))
            if droppable:
                record["extended_rows_dropped"] += 1
                continue
            if seq.get("tc_profile") != TC_PROFILE_EXTENDED:
                record["reference_rows_duplicated"] += 1
            else:
                record["extended_rows_duplicated_kept"] += 1   # (리뷰 I2) MC/DC 벡터 행 — 쌍이 벡터로 찾는다
        seen.add(key)
        kept.append(seq)
    if record["extended_rows_dropped"]:
        for i, seq in enumerate(kept):
            seq["seq_num"] = i + 1
    unit["duplicate_rows"] = record
    return kept


def summarize_duplicate_rows(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    recs = [u.get("duplicate_rows") for u in units if isinstance(u.get("duplicate_rows"), dict)]
    return {"units": len(recs),
            "reference_rows_duplicated": sum(int(r.get("reference_rows_duplicated") or 0) for r in recs),
            "units_with_reference_duplicates": sum(1 for r in recs if r.get("reference_rows_duplicated")),
            "extended_rows_dropped": sum(int(r.get("extended_rows_dropped") or 0) for r in recs),
            "extended_rows_duplicated_kept": sum(int(r.get("extended_rows_duplicated_kept") or 0) for r in recs)}


def _prune_mcdc_fill_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """(R19 리뷰 R1 W4) 근거가 붙은 뒤, 채움 행이 원래 MC/DC 행보다 **더 도출한 칸이 없으면** 뺀다(채운 입력을 함수가 읽지
    않았다 — HDPDM01 첫 판 478행 중 157행). 뒤 행의 번호는 다시 매긴다(채움 행 앞의 MC/DC 행 번호는 그대로)."""
    fills = [s for s in sequences if str(s.get("strategy") or "").startswith(MCDC_FILL_PREFIX)]
    if not fills:
        return sequences
    by_num = {s.get("seq_num"): s for s in sequences}

    def derived(seq: Dict[str, Any]) -> set:
        return {k for k, e in (seq.get("expected_evidence") or {}).items() if (e or {}).get("status") == "derived"}
    drop = {id(f) for f in fills
            if not (derived(f) - derived(by_num.get((f.get("mcdc_fill") or {}).get("from_sequence")) or {}))}
    if not drop:
        return sequences
    kept = [s for s in sequences if id(s) not in drop]
    for i, s in enumerate(kept):
        s["seq_num"] = i + 1
    report = unit.get("mcdc_fill") if isinstance(unit.get("mcdc_fill"), dict) else {}
    report["pruned"] = int(report.get("pruned") or 0) + len(drop)
    report["rows"] = int(report.get("rows") or 0) - len(drop)
    return kept


def resolve_seq_test_method(strategy: Any) -> str:
    """시퀀스 하나의 Test Method — 정본은 **시퀀스 그룹 단위**로 REQ/FI 를 나눈다."""
    return _METHOD_FI if str(strategy or "").strip() in _FI_STRATEGIES else _METHOD_REQ


def resolve_seq_gen_method(strategy: Any) -> str:
    """시퀀스 하나의 TC Generation Method — 경계값이면 `AOR/ABV`, 조건 조합이면 `AOR/AEC`."""
    s = str(strategy or "").strip()
    if s.startswith("COND_COMB_") or s.startswith("SWITCH_") or s.startswith("MCDC") or s.startswith(MCDC_FILL_PREFIX):
        return _GEN_EQUIV
    return _GEN_BOUNDARY


def determine_test_method(unit: Dict[str, Any]) -> str:
    """Infer a unit-test method label for the fixed SUTS columns.

    ⚠ 정본 시트에는 쓰이지 않는다(정본은 시퀀스 그룹별 `resolve_seq_test_method`).
    Traceability 시트·요약 통계가 아직 쓰므로 남겨 둔다.
    """
    logic = unit.get("logic_flow") or []
    has_conditions = any(n.get("type") in ("if", "switch") for n in logic if isinstance(n, dict))
    has_loops = any(n.get("type") == "loop" for n in logic if isinstance(n, dict))
    n_inputs = len(unit.get("input_vars", []))

    if has_conditions or has_loops:
        return "FNCT"
    if n_inputs > 0:
        return "FIT"
    return "RVW"


def generate_sequences(
    unit: Dict[str, Any],
    max_seq: Optional[int] = _DEFAULT_SEQ_COUNT,
    type_cache: Optional[Dict[str, str]] = None,
    extended: bool = False,
    boundary_rows: bool = True,
) -> List[Dict[str, Any]]:
    """Generate test sequences for a unit function.

    `extended`(R75 확장 프로파일): 기본 전략 목록은 **그대로 앞에** 두고(같은 이름·같은 값) 그 뒤에 덧붙인다 —
    7번째 이후의 switch case · 4번째 이후의 전역 · 8번째 이후의 MC/DC 설계 벡터 · 입력마다 최솟값/최댓값 **단독 변경**(OAT,
    조건 조합이 이미 만든 (변수, 방향)은 건너뜀). 값은 같은 `_bounds_of` 에서 오고 모르는 타입은 확장에서도 비운다.
    `max_seq=None` 이면 자르지 않는다. (R23) 입력이 같은 TC 의 앞 행과 똑같은 확장 전략 행(OAT·기본 자리를 넘는
    SWITCH/GLOBAL)은 빼고 번호를 다시 매긴다(`unit["duplicate_rows"]`). `boundary_rows=False` 는 확장에서도 경계 행 탐색(R15)을 건너뛴다 — 소스가 읽는
    입력을 찾는 중간 회차(R19 `complete_source_read_inputs`)용이고, 문서에 실리는 마지막 회차는 늘 탐색한다.

    Produces boundary-value and error-condition test sequences matching
    the reference SUTS patterns:
      Seq 1: all inputs at error-low boundary (min_inv)
      Seq 2: all inputs at minimum valid (0 for unsigned)
      Seq 3: normal mid-range values
      Seq 4: all inputs at maximum valid
      Seq 5: all inputs at error-high boundary (max_inv)
      Seq 6: mixed combination (alternating valid/boundary)
    """
    input_vars = unit.get("input_vars") or []
    output_vars = unit.get("output_vars") or []
    # (R71 N77) 파라미터 선언 타입을 전역 타입 위에 얹는다 — 예전엔 파라미터는 타입 출처가 없어 전부 이름 패턴·
    #   기본값(uint8)으로 갔다: `bool ADC_EnUser` 가 0/127/255, `U16 *Values` 가 uint8, `const ParamMapEntry_t *pt`
    #   가 0/127/255 였다(KJPDS02 실측 — unit 변수 13,081칸 중 선언은 있는데 모르는 타입 1,233 + 구조체 포인터 949).
    #   두 경로(I/O 없는 unit 의 간접 변수 경로 · 일반 경로) **모두** 이 캐시를 쓴다(리뷰 C2).
    _base_cache = type_cache if type_cache is not None else _globals_type_cache
    _ptypes = unit.get("param_types") or {}
    # (R19) 소스가 읽어 더한 입력의 **선언** 타입(번역 단위 범위에서) — 전역 표가 이미 아는 이름이면 그 표가 이긴다.
    _src_types = {k: v for k, v in (unit.get("source_input_types") or {}).items()
                  if _normalize_type(str(_base_cache.get(k) or "")) in ("", _UNKNOWN_TYPE)}
    type_cache = {**_base_cache, **_src_types, **_ptypes} if (_ptypes or _src_types) else _base_cache
    # (R73 N92) enum 값 집합이 있는 변수는 타입 `enum` — 경계값은 열거자의 최소/가운데/최대, 범위 밖은 ±1.
    _domains = unit.get("value_domains") or {}
    # (R74) 경계값의 출처 순서: **설계서 범위**(SwUDS Value Range) > enum 값 집합 > HSIS SW 값 범위 > 타입 전폭.
    #   위로 갈수록 이 변수에 대해 구체적으로 말한 문서다. 어느 출처가 정했는지는 `unit["bounds_source"]` 에 남긴다.
    _uds_info = unit.get("uds_param_info") or {}
    _hsis_rng = unit.get("hsis_bounds") or {}
    _bsrc: Dict[str, str] = {}

    # (R19 리뷰 R2) 소스 읽기가 붙인 선언 타입·열거자 — 카탈로그 **구조**(GLOBAL 행을 둘 전역)를 정할 땐 빼고 본다: 정본 규모
    #   문서가 모르던 타입이 여기서 풀리면 GLOBAL 행이 기본 영역에 끼어든다.
    _r19_typed = set(_src_types) | {k for k, d in _domains.items()
                                    if isinstance(d, dict) and d.get("source") == "translation_unit_declaration"}
    _design_cache = {**_base_cache, **_ptypes} if _ptypes else _base_cache
    # (리뷰 R3 W1) 입력 보완이 열거자를 덮어쓴 이름은 덮기 전 영역(전역 표의 값 집합)으로 본다 — 없으면 정본 규모처럼 모름
    _design_domains = unit.get("design_value_domains") or {}

    def _type_of(v: str, design: bool = False) -> str:
        r19 = design and v in _r19_typed
        if enum_bounds(_design_domains.get(v) if r19 else _domains.get(v)):
            return _ENUM_TYPE
        t = infer_variable_type(v, _design_cache if r19 else type_cache)
        if t == _UNKNOWN_TYPE:
            # 소스 선언은 모르는 타입인데 설계서가 타입을 적었으면 그것(표가 아는 이름일 때만).
            ut = _normalize_type(str((_uds_info.get(v) or {}).get("type") or ""))
            if ut and ut != _UNKNOWN_TYPE:
                return ut
            if range_bounds((_uds_info.get(v) or {}).get("range")) or range_bounds(_hsis_rng.get(v)):
                return _RANGE_TYPE
        return t

    _range_conflicts: List[str] = []
    _pointer_ranges: List[str] = []

    def _is_pointer_decl(v: str) -> bool:
        # 선언 문자열에 `*`·`[` 가 있으면 주소를 받는 자리다(`U16 *Values` · `const U8*` · `U8[]`). 경계값의 타입은 가리키는
        # 타입이다(R71). ⚠ 파라미터 선언 파서(`_param_decl_types`)는 배열 대괄호를 버려 `U8 buf[]` 가 `U8` 로 온다 — 그 경우는
        #   여전히 "문서 오류 후보" 로 세인다(값은 같다: 타입 전폭). 계획서 R76 이월 N108.
        _decl = str(type_cache.get(v) or "")
        return "*" in _decl or "[" in _decl

    def _declared(v: str) -> bool:
        # 타입이 **선언**에서 왔는가(전역 선언·파라미터 선언). 이름 패턴·기본값은 추측이다.
        return bool(_normalize_type(str(type_cache.get(v) or ""))) and _normalize_type(str(type_cache.get(v) or "")) != _UNKNOWN_TYPE

    def _fits_type(rb: Dict[str, Any], t: str, v: str, src: str) -> bool:
        # 문서의 범위가 **선언 타입이 담을 수 없는 값**이면 문서 오류다(실측: HSIS `u16g_DrvIn_MOTOR_A2_FB` U16 에
        # `0x0000 ~ 0xFFFFFU` — F 가 다섯). 그 범위는 쓰지 않고 타입 전폭으로 내려가며, 사실은 센다.
        # ⚠ 거부권은 **선언된 타입**에만 있다(리뷰 W1) — `_Flag` 라는 이름으로 `bit` 라 추측한 타입이 설계서의 `0 ~ 255` 를
        #   "문서 오류" 로 기각하면 우선순위(설계서 > 타입)가 뒤집힌다.
        tb = _TYPE_BOUNDARIES.get(t) if t in _TYPE_BOUNDARIES and t != "float" and _declared(v) else None
        if tb and (rb["min"] < tb["min"] or rb["max"] > tb["max"]):
            _msg = f"{v}({src} {rb['min']}~{rb['max']} vs {t})"
            _raw_text = str((_uds_info.get(v) or {}).get("range_text") or "") if src == "SwUDS" else ""
            if _raw_text:
                _msg += f" ← 원문 `{_raw_text}`"
            # (R76 N98) 포인터 파라미터에 문서가 적은 범위는 **주소 범위**다(`0 ~ 0xFFFFFFFF`) — 가리키는 타입(`U16`)에
            #   안 들어가는 게 당연하고 문서 오류가 아니다. 값은 예전과 같이 타입 전폭으로 가고(주소로 경계값을 만들지
            #   않는다), 계수만 "문서 오류 후보" 에서 떼어 따로 센다. 가리키는 타입에 **들어가는** 범위는 위에서 이미 쓰였다.
            _bucket = _pointer_ranges if _is_pointer_decl(v) else _range_conflicts
            if _msg not in _bucket:
                _bucket.append(_msg)
            return False
        return True

    def _bounds_of(v: str, t: str) -> Dict[str, Any]:
        rb = range_bounds((_uds_info.get(v) or {}).get("range"))
        if rb and _fits_type(rb, t, v, "SwUDS"):
            _bsrc[v] = "uds_range"
            return rb
        if t == _ENUM_TYPE:
            _bsrc[v] = "enum"
            return enum_bounds(_domains.get(v))
        hb = range_bounds(_hsis_rng.get(v))
        if hb and _fits_type(hb, t, v, "HSIS"):
            _bsrc[v] = "hsis_range"
            return hb
        b = _get_float_bounds_for_var(v) if t == "float" else get_boundary_values(t)
        _bsrc[v] = "type" if b else "unknown"
        return b

    if not input_vars and not output_vars:
        fn_name = unit.get("name", "function")
        prototype = unit.get("prototype", "")
        # ⚠ 예전엔 `"void" in prototype.split("(")[0].lower()` 였다 — 자른 앞쪽엔 **함수 이름도**
        #   들어 있어 `void_check()` 같은 이름이면 반환값이 있어도 void 로 읽힌다.
        #   판정은 `report_gen.c_return.returns_value` 단일 출처를 쓴다.
        is_void_return = not returns_value(_infer_return_type(prototype))
        calls_list = unit.get("calls_list") or []
        logic_flow = unit.get("logic_flow") or []

        # Build calls summary for description
        if calls_list:
            calls_short = calls_list[:5]
            calls_str = ", ".join(f"{c}()" for c in calls_short)
            if len(calls_list) > 5:
                calls_str += f" 외 {len(calls_list) - 5}개"
            calls_note = f" 하위 함수 [{calls_str}] 순차 호출 확인"
        else:
            calls_note = " 예외 없이 완료되며 호출 후 상태 이상 없음"

        # Extract guard condition from logic_flow for ERROR_PATH description
        guard_cond = ""
        for node in logic_flow:
            cond = str(node.get("condition", "") or node.get("text", "")).strip()
            if cond and any(op in cond for op in ("<", ">", "==", "!=", "NULL", "null")):
                guard_cond = cond[:80]
                break
        if guard_cond:
            error_desc = (
                f"{fn_name}() 에러 경로: 조건 [{guard_cond}] 위반 상태에서 호출, "
                f"에러 처리 루틴 진입 또는 안전 상태 유지 확인"
            )
        else:
            error_desc = (
                f"{fn_name}() 에러 경로: 의존 모듈/전역 변수 비정상 상태에서 호출, "
                f"에러 처리 루틴 진입 또는 안전 상태 유지 확인"
            )

        # Build inputs/expected from indirect_vars (callee global vars) if available
        indirect_vars: List[str] = unit.get("indirect_vars") or []
        normal_inputs: Dict[str, Any] = {}
        error_inputs: Dict[str, Any] = {}
        normal_expected: Dict[str, Any] = {}
        error_expected: Dict[str, Any] = {}
        # 이 경로도 타입을 기록하고(품질 리포트가 0 으로 오보하지 않게) 모르는 타입은 값을 비운다(리뷰 C2 —
        # 예전엔 `const ParamMapEntry_t *` 전역이 NORMAL 0 / ERROR 256 / 기대 255 를 받았다).
        _ind_types = {_iv: _type_of(_iv) for _iv in indirect_vars}
        unit["var_types"] = dict(_ind_types)
        unit["unknown_type_vars"] = [_iv for _iv, _t in _ind_types.items() if _t == _UNKNOWN_TYPE]
        unit["bounds_source"] = _bsrc
        unit["range_conflicts"] = _range_conflicts
        if indirect_vars:
            for _iv in indirect_vars[:4]:
                _vtype = _ind_types[_iv]
                if _vtype == _UNKNOWN_TYPE:
                    _bsrc[_iv] = "unknown"
                    continue
                _bounds = _bounds_of(_iv, _vtype)
                normal_inputs[_iv] = _bounds.get("mid", 0)
                normal_expected[_iv] = _bounds.get("mid", 0)
                error_inputs[_iv] = _bounds.get("max_inv", _bounds.get("max", 255) + 1)
                error_expected[_iv] = _bounds.get("max", 255)  # clamped/saturated

        seqs = [
            {"seq_num": 1, "inputs": normal_inputs, "expected": normal_expected,
             "strategy": "NORMAL_CALL",
             "description": f"{fn_name}() 정상 호출:{calls_note}"},
            {"seq_num": 2, "inputs": error_inputs, "expected": error_expected,
             "strategy": "ERROR_PATH",
             "description": error_desc},
            {"seq_num": 3, "inputs": {}, "expected": {},
             "strategy": "REPEAT_CALL",
             "description": (
                 f"{fn_name}() 반복 호출 안정성: 100회 연속 호출 후 메모리 누수 없음, "
                 f"시스템 상태 일관성 유지"
             )},
        ]
        if not is_void_return:
            seqs.append({"seq_num": 4, "inputs": {}, "expected": {},
                         "strategy": "RETURN_CHECK",
                         "description": f"{fn_name}() 반환값 검증: 반환값이 정의된 범위 내 유효한 값임을 확인"})
        return apply_sequence_evidence(unit, seqs[:max_seq])

    var_types = {v: _type_of(v) for v in input_vars}
    var_bounds = {v: _bounds_of(v, t) for v, t in var_types.items()}

    out_types = {v: _type_of(v) for v in output_vars}
    out_bounds = {v: _bounds_of(v, t) for v, t in out_types.items()}
    # 모르는 타입의 변수 — 값을 지어내지 않고 시퀀스에서 **비운다**. 어느 칸이 왜 비었는지는 unit 에 남겨 품질
    # 리포트가 센다(`unknown_type_vars`, 입력·출력·간접 전역을 한 번씩). 타입 분포도 같이 남긴다(라이브 대조용).
    _ind_types = {gv: _type_of(gv) for gv in (unit.get("indirect_vars") or [])}
    unit["var_types"] = {**var_types, **out_types, **_ind_types}
    _unknown_vars = [v for v, t in unit["var_types"].items() if t == _UNKNOWN_TYPE]
    unit["unknown_type_vars"] = _unknown_vars
    for _gv, _gt in _ind_types.items():
        _bounds_of(_gv, _gt)       # 간접 전역의 출처도 남긴다(값은 쓰는 자리에서 다시 구한다)
    unit["bounds_source"] = _bsrc
    unit["range_conflicts"] = _range_conflicts
    unit["pointer_address_ranges"] = _pointer_ranges

    logic_flow = unit.get("logic_flow") or []

    strategies = [
        ("BV_MIN_INV", "min_inv"),
        ("BV_MIN",     "min"),
        ("BV_MID",     "mid"),
        ("BV_MAX",     "max"),
        ("BV_MAX_INV", "max_inv"),
        ("MIXED",      None),
    ]

    # ── Additional strategies for branch coverage ──
    # GAP 1: Condition combination — toggle each input while others stay at mid
    # (R71 N77) 토글 대상은 값을 만들 수 있는(타입을 아는) 입력뿐이다 — 모르는 타입을 토글하면 값이 비어 중간값
    #   시퀀스와 같은 행이 하나 더 생기고 라벨만 "pt_Entry=최솟값" 이라 말한다.
    # (R19) 카탈로그의 **구조**(조건 조합·switch·루프·MC/DC 자리)는 설계 입력 목록으로 정한다. 확장 프로파일이 소스가 읽어 더한
    #   입력은 기본 카탈로그의 자리·순서를 바꾸지 않는다(R75 포함 관계 — 리뷰 R1 C1: 더한 입력이 조건 조합 행을 기본 영역에 끼워
    #   MC/DC 자리를 밀었다). 그 행에서 더한 입력은 고정값(`_fill_all`)이고 극값은 확장 행(OAT·경계)에서만 움직인다.
    _design_inputs = ([v for v in unit["design_input_vars"] if v in input_vars]
                      if isinstance(unit.get("design_input_vars"), list) else list(input_vars))
    _added_inputs = [v for v in input_vars if v not in set(_design_inputs)]
    _design_toggles = [v for v in _design_inputs if var_types.get(v) != _UNKNOWN_TYPE]
    _toggle_vars = _design_toggles + [v for v in _added_inputs if var_types.get(v) != _UNKNOWN_TYPE]
    _cond_count = min(4, len(_design_toggles)) if len(_design_inputs) >= 2 else 0
    for toggle_idx in range(_cond_count):
        strategies.append((f"COND_COMB_{toggle_idx}", f"_cond_{toggle_idx}"))

    # GAP 2: Switch-case — generate TC per enum/case value from logic_flow
    _all_switch = _extract_switch_cases(logic_flow, _design_inputs)
    _extra_switch = _all_switch if extended else _all_switch[:_BASE_SWITCH_SLOTS]
    for sw_idx in range(min(_BASE_SWITCH_SLOTS, len(_extra_switch))):
        strategies.append((f"SWITCH_{sw_idx}", f"_switch_{sw_idx}"))

    # GAP 3: Loop boundary — 0/1/max iterations for loop-containing functions
    _has_loop = any(
        str(n.get("type", "")).lower() == "loop" for n in logic_flow if isinstance(n, dict)
    )
    _loop_var = ""
    if _has_loop:
        for n in logic_flow:
            if str(n.get("type", "")).lower() == "loop":
                cond = str(n.get("condition", ""))
                for iv in _design_inputs:
                    if iv.lower() in cond.lower():
                        _loop_var = iv
                        break
                break
        if not _loop_var and _design_inputs:
            # 값을 만들 수 있는 첫 입력 — 모르는 타입이면 0/1/최댓값을 못 넣어 루프 시퀀스가 빈 행이 된다.
            _loop_var = next((v for v in _design_inputs if var_types.get(v) != _UNKNOWN_TYPE), "")
        if _loop_var:
            strategies.append(("LOOP_ZERO", "_loop_0"))
            strategies.append(("LOOP_ONE", "_loop_1"))
            strategies.append(("LOOP_MAX", "_loop_max"))

    # GAP 4: Global state combination — toggle indirect (global) vars
    indirect_vars: List[str] = unit.get("indirect_vars") or []
    _extra_globals: List[str] = []
    if indirect_vars:
        # 모르는 타입의 전역은 토글 대상이 아니다(리뷰 C2 — `void *` 전역이 `{pt_G: 0}` 로 섰다).
        _known_globals = [g for g in indirect_vars if _type_of(g, design=True) != _UNKNOWN_TYPE]
        for gv in (_known_globals if extended else _known_globals[:_BASE_GLOBAL_SLOTS]):
            _extra_globals.append(gv)
            if len(_extra_globals) <= _BASE_GLOBAL_SLOTS:
                strategies.append((f"GLOBAL_{len(_extra_globals)-1}", f"_global_{len(_extra_globals)-1}"))

    # GAP 5: Void side-effect — for functions with inputs but no outputs,
    # add sequence using indirect_vars as expected outputs
    if _design_inputs and not output_vars and indirect_vars:
        strategies.append(("VOID_SIDE_EFFECT", "_void_se"))

    # GAP 6: MC/DC — 결정식을 **실제로 평가해** 찾은 unique-cause 독립 영향 쌍의 입력 벡터(`generators.mcdc_design`).
    # ⚠ 예전 경로(regex `_extract_mcdc_conditions`)는 "전부 참 + 하나만 거짓(나머지 중간값)" 을 만들어 OR 식에서
    #   독립 영향이 0 이었다(`a>10 || b>20` 에서 a 를 뒤집어도 b 가 참이라 결과가 안 바뀐다) — 기법 주장만 있고 쌍이 없었다.
    #   도메인은 **선언**에서 온 것만 쓴다(이름 패턴 추측 금지). 못 푸는 결정은 쌍 없이 사유를 남기고 분모에 남는다.
    # (R19) 설계 입력 목록 위에서 — 기본 자리(`_BASE_MCDC_SLOTS`)의 벡터가 정본 규모 문서와 같다. 더한 입력만 읽는 결정은
    #   예전처럼 `decision_variable_not_in_unit_inputs` 로 남는다(확장 MC/DC 설계는 후속).
    _mcdc_unit = dict(unit, input_vars=list(_design_inputs)) if _added_inputs else unit
    _mcdc_report = build_mcdc_design(_mcdc_unit, declared_domains=_mcdc_declared_domains(
        _design_inputs, _type_of, _domains, _declared, _is_pointer_decl, set(_ptypes)))
    unit["mcdc_design"] = _mcdc_report
    _mcdc_vectors: List[Dict[str, int]] = list(_mcdc_report.get("selected_inputs") or [])
    _mcdc_roles = _mcdc_vector_roles(_mcdc_report)
    for mc_idx in range(min(len(_mcdc_vectors), _BASE_MCDC_SLOTS)):
        strategies.append((f"MCDC_{mc_idx}", f"_mcdc_{mc_idx}"))

    # (R75) 확장 — 위까지가 기본 카탈로그(최대 30)다. 확장은 그 **뒤에만** 붙는다(기본 문서와 포함 관계).
    _base_strategy_count = len(strategies)
    unit["base_strategy_count"] = _base_strategy_count
    if extended:
        for sw_idx in range(_BASE_SWITCH_SLOTS, len(_extra_switch)):
            strategies.append((f"SWITCH_{sw_idx}", f"_switch_{sw_idx}"))
        for gv_idx in range(_BASE_GLOBAL_SLOTS, len(_extra_globals)):
            strategies.append((f"GLOBAL_{gv_idx}", f"_global_{gv_idx}"))
        for mc_idx in range(_BASE_MCDC_SLOTS, len(_mcdc_vectors)):
            strategies.append((f"MCDC_{mc_idx}", f"_mcdc_{mc_idx}"))
        # 단독 경계(OAT): 입력 하나만 경계로, 나머지는 중간값. 입력이 하나뿐이면 BV_MIN/BV_MAX 가 이미 그것이다.
        if len(input_vars) >= 2:
            for t_idx in range(len(_toggle_vars)):
                if t_idx < len(_design_toggles) and len(_design_inputs) < 2:
                    continue   # (R19 리뷰 R2 W2') 설계 입력이 하나면 BV_MIN/BV_MAX 가 이미 그 단독 변경이다
                for side in ("min", "max"):
                    # 조건 조합(앞 4개)이 이미 만든 (변수, 방향): 짝수 번째=min, 홀수 번째=max.
                    if t_idx < _cond_count and side == ("min" if t_idx % 2 == 0 else "max"):
                        continue
                    strategies.append((f"OAT_{t_idx}_{side.upper()}", f"_oat_{t_idx}_{side}"))

    # Pre-compute clamp/guard analysis once (avoid repeated DFS per strategy)
    check_vars = output_vars or input_vars
    _has_any_clamp = any(_flow_has_clamp_pattern(logic_flow, v) for v in check_vars)
    _has_any_guard = any(_flow_has_guard_clause(logic_flow, v) for v in check_vars)

    def _resolve_inv_label(sname: str) -> str:
        """Resolve 'error/saturation' ambiguity using pre-computed flow analysis."""
        if sname not in ("BV_MIN_INV", "BV_MAX_INV"):
            return _STRAT_LABEL.get(sname, sname)
        direction = "하한 초과 (경계-1)" if sname == "BV_MIN_INV" else "상한 초과 (경계+1)"
        if _has_any_clamp and _has_any_guard:
            return f"유효 {direction}: 포화(clamp) 및 가드 조건 처리 확인"
        elif _has_any_clamp:
            return f"유효 {direction}: 포화(saturation) 처리 확인"
        elif _has_any_guard:
            return f"유효 {direction}: 가드 조건에 의한 에러 처리 확인"
        else:
            return f"유효 {direction}: 방어 처리 확인 (포화 추정)"

    _fill_all: Dict[str, int] = {}
    if extended:
        from generators.boundary_rows import blank_fill
        _fill_domains = {v: d for v, d in _boundary_domains(unit, input_vars, var_types, var_bounds,
                                                            set(_unknown_vars)).items()
                         if var_types.get(v) == _ENUM_TYPE or _declared(v)}
        _fill_all = blank_fill(_fill_domains, {v: m for v in _fill_domains
                                               if isinstance(m := (var_bounds.get(v) or {}).get("mid"), int)
                                               and not isinstance(m, bool)})

    sequences: List[Dict[str, Any]] = []
    for idx, (strat_name, bound_key) in enumerate(strategies if max_seq is None else strategies[:max_seq]):
        seq_num = idx + 1
        inp_vals: Dict[str, Any] = {}
        exp_vals: Dict[str, Any] = {}

        mcdc_label = ""
        if bound_key and bound_key.startswith("_mcdc_"):
            # MC/DC 설계 벡터 — 값은 엔진이 식을 평가해 고른 그대로다(중간값·임의 보정 없음). 기대값은 이 벡터가
            # 말해 주지 않는다: 결정 결과 ≠ 출력값이라 자리만 두고 `apply_sequence_evidence` 가 근거를 붙인다.
            vector = _mcdc_vectors[int(bound_key.split("_")[-1])]
            # (R81) 결정이 읽지 않는데 도메인을 모르는 입력(포인터·배열·구조체)은 벡터에 없다 — 칸을 비운다(추측값 금지).
            #   exporter 는 빈 칸을 "키 없음" 으로 읽어 MCDC Design 시트의 벡터 JSON 과 그대로 맞춘다.
            for v in input_vars:
                if v in vector:
                    inp_vals[v] = vector[v]
            for v in output_vars:
                exp_vals[v] = f"{_VERIFY_NEEDED_PREFIX} mcdc_design_vector"
            # 라벨은 쌍이 행 상한 뒤에도 살아남았는지 알아야 쓸 수 있다 — finalize 뒤에 다시 쓴다(리뷰 C1).
            mcdc_label = "MC/DC 설계 벡터"
        elif bound_key and bound_key.startswith("_loop_"):
            # Loop boundary: set loop counter var to 0 / 1 / max
            loop_key = bound_key.split("_")[-1]
            for v in input_vars:
                bnd = var_bounds.get(v, _DEFAULT_BOUNDARY)
                if v == _loop_var:
                    if loop_key == "0":
                        inp_vals[v] = _format_test_value(0, var_types.get(v, "uint8_t"))
                    elif loop_key == "1":
                        inp_vals[v] = _format_test_value(1, var_types.get(v, "uint8_t"))
                    else:  # max
                        inp_vals[v] = _format_test_value(min(bnd.get("max", 255), 255), var_types.get(v, "uint8_t"))
                else:
                    inp_vals[v] = _format_test_value(bnd.get("mid", 0), var_types.get(v, "uint8_t"))
            for v in output_vars:
                bnd = out_bounds.get(v, _DEFAULT_BOUNDARY)
                exp_vals[v] = _format_test_value(bnd.get("mid", 0), out_types.get(v, "uint8_t"))
        elif bound_key and bound_key.startswith("_global_"):
            # Global state: toggle indirect var to min, inputs at mid
            gv_idx = int(bound_key.split("_")[-1])
            for v in input_vars:
                bnd = var_bounds.get(v, _DEFAULT_BOUNDARY)
                inp_vals[v] = _format_test_value(bnd.get("mid", 0), var_types.get(v, "uint8_t"))
            # Add the global var as input with boundary value
            if gv_idx < len(_extra_globals):
                gv = _extra_globals[gv_idx]
                gv_type = _ind_types.get(gv) or _type_of(gv)
                gv_bnd = _bounds_of(gv, gv_type)
                inp_vals[gv] = _format_test_value(gv_bnd.get("min", 0), var_types.get(gv, gv_type) if gv in var_types else gv_type)
            for v in output_vars:
                bnd = out_bounds.get(v, _DEFAULT_BOUNDARY)
                exp_vals[v] = _format_test_value(bnd.get("mid", 0), out_types.get(v, "uint8_t"))
        elif bound_key == "_void_se":
            # Void side-effect: input at boundary, check globals as expected
            for v in input_vars:
                bnd = var_bounds.get(v, _DEFAULT_BOUNDARY)
                inp_vals[v] = _format_test_value(bnd.get("max_inv", bnd.get("max", 255) + 1), var_types.get(v, "uint8_t"))
            for gv in _extra_globals[:_BASE_GLOBAL_SLOTS]:
                gv_type = _ind_types.get(gv) or _type_of(gv)
                gv_bnd = _bounds_of(gv, gv_type)
                exp_vals[gv] = _format_test_value(gv_bnd.get("mid", 0), gv_type)
        elif bound_key and bound_key.startswith("_cond_"):
            # Condition combination: toggle one input to min, others stay at mid
            toggle_idx = int(bound_key.split("_")[-1])
            _toggle_var = _toggle_vars[toggle_idx] if toggle_idx < len(_toggle_vars) else ""
            for v in input_vars:
                bnd = var_bounds.get(v, _DEFAULT_BOUNDARY)
                if v == _toggle_var:
                    raw = bnd.get("min", 0) if toggle_idx % 2 == 0 else bnd.get("max", 0)
                else:
                    raw = bnd.get("mid", 0)  # others at mid
                inp_vals[v] = _format_test_value(raw, var_types.get(v, "uint8_t"))
            for v in output_vars:
                bnd = out_bounds.get(v, _DEFAULT_BOUNDARY)
                exp_vals[v] = _format_test_value(bnd.get("mid", 0), out_types.get(v, "uint8_t"))
        elif bound_key and bound_key.startswith("_oat_"):
            # (R75) 단독 경계: 한 입력만 최솟값/최댓값, 나머지는 중간값
            _, _, _oi, _oside = bound_key.split("_")
            _oat_var = _toggle_vars[int(_oi)] if int(_oi) < len(_toggle_vars) else ""
            for v in input_vars:
                bnd = var_bounds.get(v, _DEFAULT_BOUNDARY)
                raw = bnd.get(_oside, 0) if v == _oat_var else bnd.get("mid", 0)
                inp_vals[v] = _format_test_value(raw, var_types.get(v, "uint8_t"))
            for v in output_vars:
                bnd = out_bounds.get(v, _DEFAULT_BOUNDARY)
                exp_vals[v] = _format_test_value(bnd.get("mid", 0), out_types.get(v, "uint8_t"))
        elif bound_key and bound_key.startswith("_switch_"):
            # Switch-case: set target var to specific case value
            sw_idx = int(bound_key.split("_")[-1])
            if sw_idx < len(_extra_switch):
                sw_var, sw_val, _ = _extra_switch[sw_idx]
                for v in input_vars:
                    bnd = var_bounds.get(v, _DEFAULT_BOUNDARY)
                    if v == sw_var:
                        inp_vals[v] = _format_test_value(sw_val, var_types.get(v, "uint8_t"))
                    else:
                        inp_vals[v] = _format_test_value(bnd.get("mid", 0), var_types.get(v, "uint8_t"))
                for v in output_vars:
                    bnd = out_bounds.get(v, _DEFAULT_BOUNDARY)
                    exp_vals[v] = _format_test_value(bnd.get("mid", 0), out_types.get(v, "uint8_t"))
        elif bound_key:
            for v in input_vars:
                bnd = var_bounds.get(v, _DEFAULT_BOUNDARY)
                raw = bnd.get(bound_key, 0)
                inp_vals[v] = _format_test_value(raw, var_types.get(v, "uint8_t"))
            for v in output_vars:
                bnd = out_bounds.get(v, _DEFAULT_BOUNDARY)
                raw = _infer_expected_for_strategy(
                    bnd, bound_key, out_types.get(v, "uint8_t"), logic_flow, v
                )
                exp_vals[v] = _format_test_value(raw, out_types.get(v, "uint8_t"))
        else:
            for i, v in enumerate(input_vars):
                bnd = var_bounds.get(v, _DEFAULT_BOUNDARY)
                key = "min" if i % 2 == 0 else "max"
                raw = bnd.get(key, 0)
                inp_vals[v] = _format_test_value(raw, var_types.get(v, "uint8_t"))
            for v in output_vars:
                bnd = out_bounds.get(v, _DEFAULT_BOUNDARY)
                raw = bnd.get("mid", 0)
                exp_vals[v] = _format_test_value(raw, out_types.get(v, "uint8_t"))

        # (R19) 더한 입력은 이 행의 전략이 움직이는 대상이 아니면 고정값 — 설계 열의 값은 정본 규모 문서와 같다. BV_MIN 이 더한
        #   입력까지 형 끝값으로 밀면 전에 도출하던 칸이 미정의 동작으로 사라졌다(리뷰 R1 W3: 2 unit 7칸). MC/DC 벡터는 그대로.
        _fixed: List[str] = []
        if _added_inputs and not (bound_key or "").startswith("_mcdc_"):
            _target = ""
            if (bound_key or "").startswith("_oat_"):
                _oi = int(bound_key.split("_")[2])
                _target = _toggle_vars[_oi] if _oi < len(_toggle_vars) else ""
            elif (bound_key or "").startswith("_global_"):
                # (리뷰 R2 C1) GLOBAL 행이 최솟값으로 움직이는 전역이 더한 입력이면 그 값을 덮지 않는다(정본 행의 자극)
                _gi = int(bound_key.split("_")[-1])
                _target = _extra_globals[_gi] if _gi < len(_extra_globals) else ""
            for v in _added_inputs:
                if v == _target:
                    continue
                if v in _fill_all:
                    inp_vals[v] = _format_test_value(_fill_all[v], var_types.get(v, "uint8_t"))
                    _fixed.append(v)
                else:
                    inp_vals.pop(v, None)

        # (R71 N77) 모르는 타입의 변수는 값을 비운다 — `{}` 경계에서 `.get(key, 0)` 로 만든 0 은 값이 아니라 자리표시다.
        for _vals in (inp_vals, exp_vals):
            for _k in [k for k in _vals if k in _unknown_vars]:
                # (R81 리뷰 W5) MC/DC 벡터 값은 엔진이 **선언**에서 푼 도메인에서 왔다 — SUTS 타입 표가 못 풀었다고 지우면
                #   finalize 가 짝을 못 찾아 "절단" 으로, 공란 라벨이 "결정 무관" 으로 오표기한다.
                if _vals is inp_vals and bound_key and bound_key.startswith("_mcdc_"):
                    continue
                _vals.pop(_k, None)

        # Build human-readable description showing actual variable names and values
        label = _resolve_inv_label(strat_name) if strat_name in _STRAT_LABEL else (
            _get_strategy_label(strat_name, _toggle_vars if strat_name.startswith(("COND_COMB_", "OAT_")) else input_vars,
                                _extra_switch, _loop_var if _has_loop else "", _extra_globals)
        )
        if mcdc_label:
            label = mcdc_label
        inp_parts = [f"{v}={inp_vals[v]}" for v in input_vars if v in inp_vals]
        exp_parts = [f"{v}={exp_vals[v]}" for v in output_vars if v in exp_vals]
        # Include extra expected vars (e.g., globals from VOID_SIDE_EFFECT)
        for v in exp_vals:
            if v not in output_vars:
                exp_parts.append(f"{v}={exp_vals[v]}")
        desc_lines = [label]
        if _fixed:
            desc_lines.append("소스가 읽어 더한 입력(설계서 입력 표 밖 · 이 행에선 고정값): "
                              + ", ".join(f"{v}={inp_vals[v]}" for v in _fixed))
        if inp_parts:
            desc_lines.append("Input: " + ", ".join(inp_parts))
        if exp_parts:
            desc_lines.append("Expected: " + ", ".join(exp_parts))
        description = "\n".join(desc_lines)

        sequences.append({
            "seq_num": seq_num,
            "inputs": inp_vals,
            "expected": exp_vals,
            "strategy": strat_name,
            "description": description,
        })
        if idx >= _base_strategy_count:
            # 확장 전략의 표시는 **만든 자리에서** 단다 — 이름을 되읽어 추정하지 않는다(리뷰 W2·X5).
            sequences[-1]["tc_profile"] = TC_PROFILE_EXTENDED

    # 행 상한(`strategies[:max_seq]`)을 **적용한 뒤** 쌍을 다시 검증한다 — 한쪽 행만 남은 쌍은 `truncated` 로 공시되고
    # 커버리지 주장에서 빠진다. MC/DC 행끼리만 묶는다(같은 입력의 BV 행을 쌍 구성원으로 잡으면 설계 근거가 섞인다).
    # (R23) 같은 TC 안에서 입력이 앞 행과 똑같은 행 — 기대값도 같아(결정적 oracle) 정보가 없다. 확장 전략 행(OAT·기본 자리를
    #   넘는 SWITCH/GLOBAL)은 근거 계산 전에 빼고, 정본 규모 카탈로그 행은 R75 포함 관계 때문에 두되 센다. MC/DC 행은 쌍이 벡터로
    #   행을 찾으므로, 경계·채움 행은 만들 때 이미 겹침을 피하므로 대상이 아니다. ⚠ finalize **앞**에서 한다 — finalize 가 쌍에
    #   행 번호(`seq_a`/`seq_b`)를 적어 두므로, 뒤에서 번호를 다시 매기면 MCDC Design 시트가 엉뚱한 행을 가리킨다(리뷰 R1 C1).
    sequences = _drop_duplicate_rows(unit, sequences, extended)
    _mcdc_rows = [s for s in sequences if str(s.get("strategy") or "").startswith("MCDC_")]
    # (R2c) 함수 실행 모델로 설계한 결정(`evaluation=source_path`)은 행 입력으로 oracle 을 다시 돌려 검증한다 — unit 필요.
    finalize_mcdc_design(_mcdc_report, _mcdc_rows, _mcdc_unit)
    if _added_inputs:
        # (리뷰 R2 W3') 설계 입력 목록 위의 MC/DC 라 더한 입력을 읽는 결정은 거절된다 — 확장 문서엔 그 열이 있으니 "입력 목록 밖"
        #   이라 쓰면 거짓이다. 사유를 바꿔 적는다(확장 MC/DC 설계는 후속).
        _added_set = set(_added_inputs)
        for _d in _mcdc_report.get("decisions") or []:
            _r = str(_d.get("reason") or "")
            if _r.startswith("decision_variable_not_in_unit_inputs:") and _r.split(":", 1)[1] in _added_set:
                _d["reason"] = "decision_reads_source_read_input_not_designed:" + _r.split(":", 1)[1]
    for _row in _mcdc_rows:
        # (리뷰 C1) "독립 영향 쌍" 은 **두 행이 모두 남아 재검증을 통과한** 쌍(`seq["mcdc_design"]`)에만 쓴다. 짝 행이 잘렸거나
        # 무효가 된 벡터는 그 사실을 라벨에 적는다 — 예전엔 절단 전 라벨이 남아 MCDC Design 시트(truncated)와 모순됐다.
        _roles = _mcdc_roles.get(_mcdc_vector_key({k: _row["inputs"].get(k) for k in _row["inputs"]}), [])
        _lines = str(_row.get("description") or "").split("\n")
        _lines[0] = _mcdc_vector_label(_row.get("mcdc_design") or [],
                                       [r["pair"].get("retained_status", "") for r in _roles])
        _blank = [v for v in input_vars if v not in _row["inputs"]]
        if _blank:
            # (R81) 결정이 읽지 않고 도메인도 모르는 입력은 비운 칸이다 — 값이 없다는 것을 행에서 말한다.
            _lines[0] += f" · 설계 밖 입력(공란, 결정 무관·도메인 미상): {', '.join(_blank)}"
        _row["description"] = "\n".join(_lines)
    if extended:
        # (R19) MC/DC 벡터가 비운 결정 무관 입력을 채운 동반 행(벡터 행·쌍 주장은 그대로). 선택 확장이라 실패해도 문서는 만든다.
        try:
            _append_mcdc_fill_rows(unit, sequences, input_vars, output_vars, var_types, _fill_all)
        except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
            _logger.warning("SUTS MC/DC 채움 행 실패(%s): %s", unit.get("name"), exc, exc_info=True)
            sequences[:] = [s for s in sequences if not str(s.get("strategy") or "").startswith(MCDC_FILL_PREFIX)]
            unit["mcdc_fill"] = {"error": type(exc).__name__}
    sequences = apply_sequence_evidence(unit, sequences)
    if not extended:
        return sequences
    sequences = _prune_mcdc_fill_rows(unit, sequences)
    # (R15) 경계 행 — 확장 프로파일에만. 출력이 바뀌는 인접 입력 두 값을 행으로 **더한다**(기존 행은 옮기지 않는다, R4b 교훈).
    #   `boundary_rows=False` 면 탐색에 쓸 문맥만 남기고 호출자가 마지막에 한 번 붙인다(`append_boundary_rows`, R19 리뷰 W6).
    ctx = {"input_vars": list(input_vars), "output_vars": list(output_vars), "var_types": dict(var_types),
           "var_bounds": dict(var_bounds), "unknown": sorted(_unknown_vars)}
    if boundary_rows:
        return append_boundary_rows(unit, sequences, ctx)
    unit["_boundary_ctx"] = ctx
    return sequences


def append_boundary_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]],
                         ctx: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """(R15/R19) 근거가 붙은 시퀀스 뒤에 경계 행을 더하고 **새 행에만** 근거를 붙인다(행마다 독립이라 결과는 한 번에 붙인 것과
    같다). `ctx` 가 없으면 `generate_sequences(..., boundary_rows=False)` 가 unit 에 남긴 문맥을 꺼낸다(없으면 그대로 — 입출력
    없는 unit 경로)."""
    ctx = ctx if ctx is not None else unit.pop("_boundary_ctx", None)
    unit.pop("_boundary_ctx", None)
    if not ctx:
        return sequences
    n = len(sequences)
    _append_boundary_rows(unit, sequences, ctx["input_vars"], ctx["output_vars"], ctx["var_types"], ctx["var_bounds"],
                          set(ctx["unknown"]))
    if len(sequences) > n:
        sequences[n:] = apply_sequence_evidence(unit, sequences[n:])
    return sequences


# ── (R19) 소스가 읽는 입력 ──────────────────────────────────────────────────────────────────────────────────────
# oracle 이 기대값을 못 낸 사유 `initial_value_not_in_inputs:X` = 이 행으로 함수를 돌리면 X 를 **쓰기 전에 읽는데** 행이 X 의
# 값을 주지 않았다. 시험 입력 목록(설계서 입력 표·소스 분석)이 그 객체를 빠뜨렸다는 뜻이다. 실측(R17 확장 생성본 · R4 하네스):
# 정본만 판별한 변이 HDPDM01 347 중 244 · KJPDS02_PV 257 중 124 가 이런 함수에 있다 — 예: HDPDM01 SwUDS v1.07 이
# `s_MoveStartClose_GainMeasure` 의 입력으로 **Open** gain 을 적었고 소스는 **Close** gain 을 읽는다(정본 SUTS 는 소스를 따랐다).
_SOURCE_READ_RE = re.compile(r"initial_value_not_in_inputs:([A-Za-z_]\w*(?:\[\d+\])?)(?![\w.\[])")
_SOURCE_READ_ROUNDS = 3


def source_read_names(sequences: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """행이 값을 주지 않았는데 함수가 초기값을 읽은 이름 → {"slots": 칸 수, "sequences": [행 번호…]}(기대값 근거의 사유에서).

    멤버 경로(`s.a`)·2차원 첨자는 이름으로 싣지 않는다(시험 입력 한 칸으로 줄 수 있는 모양이 아니다)."""
    out: Dict[str, Dict[str, Any]] = {}
    for seq in sequences:
        for ev in (seq.get("expected_evidence") or {}).values():
            for name in _SOURCE_READ_RE.findall(str((ev or {}).get("reason") or "")):
                rec = out.setdefault(name, {"slots": 0, "sequences": []})
                rec["slots"] += 1
                if seq.get("seq_num") not in rec["sequences"]:
                    rec["sequences"].append(seq.get("seq_num"))
    return out


_SCOPE_TYPE_KEYS = {(8, False): "uint8_t", (8, True): "int8_t", (16, False): "uint16_t", (16, True): "int16_t",
                    (32, False): "uint32_t", (32, True): "int32_t"}


def scope_input_types(unit: Dict[str, Any], names: List[str]
                      ) -> Tuple[Dict[str, str], Dict[str, Dict[str, Any]], Dict[str, str]]:
    """(R19) 번역 단위 범위가 **선언으로** 아는 입력의 타입 — (경계값 표의 타입 키, enum 값 집합, 못 정한 이름의 사유).

    범위가 해석한 타입의 폭·부호로 키를 정하고(표가 모르는 typedef 이름도 해석된 타입으로 읽는다), enum 은 그 번역 단위의
    열거자 값 집합을 준다(`mcdc_design._scope_domain` — 같은 이름의 static 이 두 unit 에 있어도 이 unit 의 것). 사유:
    `type_not_resolved`(범위가 타입을 못 풂) · `no_boundary_table_for_type`(풀렸지만 64비트 등 경계값 표에 없음) ·
    `enum_values_unresolved`. 추측하지 않는다."""
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    types: Dict[str, str] = {}
    domains: Dict[str, Dict[str, Any]] = {}
    reasons: Dict[str, str] = {}
    if not scope:
        return types, domains, {n: "no_project_scope" for n in names}
    from generators import c_project_context as cpc
    from generators.mcdc_design import _scope_domain
    for name in names:
        base, _, rest = name.partition("[")
        table = (scope.get("arrays") if rest else scope.get("globals")) or {}
        rec = table.get(base)
        t = rec.get("type") if isinstance(rec, dict) else None
        if not isinstance(t, dict):
            reasons[name] = "type_not_resolved"
            continue
        if rec.get("volatile") or rec.get("const") or cpc.is_float(t):
            reasons[name] = "not_a_settable_integer"
            continue
        if t.get("enum"):
            try:
                dom = _scope_domain(t, str(rec.get("typename") or ""), scope, "enum_declaration")
            except (cpc.Unresolved, KeyError, TypeError):
                reasons[name] = "enum_values_unresolved"
                continue
            domains[name] = {"values": list(dom["values"]), "source": "translation_unit_declaration"}
            continue
        key = "bool" if t.get("kind") == "_Bool" else _SCOPE_TYPE_KEYS.get((t.get("bits"), bool(t.get("signed"))), "")
        if key:
            types[name] = key
        else:
            reasons[name] = "no_boundary_table_for_type"
    return types, domains, reasons


def _source_object_decl(scope: Dict[str, Any], name: str) -> Tuple[Optional[str], str]:
    """(선언 타입 이름, "") 또는 (None, 더하지 않는 사유). 번역 단위 범위의 **프로그램 객체**만 — 지역·매개변수·모르는 이름은
    입력으로 더하지 않는다. 원소(`a[3]`)는 1차원 배열 표의 원소 타입, 길이를 알면 범위 안일 때만."""
    base, _, rest = name.partition("[")
    if rest:
        rec = (scope.get("arrays") or {}).get(base)
        if not isinstance(rec, dict):
            return None, "element_of_unmodeled_array"
        length = rec.get("length")
        if isinstance(length, int) and not 0 <= int(rest.rstrip("]")) < length:
            return None, "element_out_of_range"
    else:
        rec = (scope.get("globals") or {}).get(base)
        if not isinstance(rec, dict):
            return None, ("array_object" if base in (scope.get("arrays") or {}) else "not_a_program_object")
    if rec.get("const"):
        return None, "const_object"
    if rec.get("volatile"):
        return None, "volatile_object"
    from generators.c_project_context import is_float
    if isinstance(rec.get("type"), dict) and is_float(rec["type"]):
        return None, "float_object"
    typename = str(rec.get("typename") or "").strip()
    if not typename:
        return None, "no_declared_type"
    return typename, ""


def complete_source_read_inputs(unit: Dict[str, Any], sequences: List[Dict[str, Any]],
                                regenerate: Callable[[], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """(R19, 확장 프로파일) 소스가 읽는데 입력 목록에 없는 프로그램 객체를 **선언 타입으로** 입력 열에 더하고 다시 만든다.

    회차마다 `source_read_names` 가 찾은 이름 중 번역 단위의 스칼라 객체(또는 1차원 배열 원소)만 더한다. 더한 입력은 기본 카탈로그
    행에선 고정값이고(구조는 `unit["design_input_vars"]` = 설계 입력 목록으로 정해진다 — `generate_sequences`), OAT·경계 행에서
    선언 타입(enum 은 그 번역 단위의 열거자) 범위를 움직인다. 더한 입력이 새 경로를 열어 또 다른 이름이 보이면 다음 회차(최대
    `_SOURCE_READ_ROUNDS`)에서 더한다. `regenerate()` 는 경계 행 없이 다시 만든다 — 경계 행은 호출자가 마지막에 한 번 붙인다.
    입출력이 없는 unit(전략 목록 대신 호출 시퀀스를 쓰는 경로)은 건드리지 않는다. 기록은 `unit["source_read_inputs"]`:
    더한 이름(처음 본 칸 수·회차·타입) · 더하지 않은 이름과 사유 · 마지막 행들에서도 값이 없는 이름(`remaining`)."""
    record: Dict[str, Any] = {"added": {}, "not_added": {}, "rounds": 0, "remaining": {}}
    unit["source_read_inputs"] = record
    if not (unit.get("input_vars") or unit.get("output_vars")):
        record["not_added"] = {n: "unit_without_inputs_or_outputs" for n in source_read_names(sequences)}
        return sequences
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    max_inp = _INPUT_COL_END - _INPUT_COL_START + 1
    for _round in range(_SOURCE_READ_ROUNDS):
        found = source_read_names(sequences)
        inputs = list(unit.get("input_vars") or [])
        new: List[str] = []
        for name, rec in sorted(found.items(), key=lambda kv: (-kv[1]["slots"], kv[0])):
            if name in inputs or name in record["added"] or name in record["not_added"]:
                continue   # 열은 있는데 그 행이 비운 칸(MC/DC 벡터) — 채움 행의 몫
            typename, why = _source_object_decl(scope, name) if scope else (None, "no_project_scope")
            if not why:
                key, enum, reasons = scope_input_types(unit, [name])
                why = reasons.get(name, "")
            if why:
                record["not_added"][name] = why
                continue
            if len(inputs) + len(new) >= max_inp:
                record["not_added"][name] = "input_columns_full"
                continue
            new.append(name)
            record["added"][name] = {"slots": rec["slots"], "round": _round + 1, "type": typename,
                                     "value_type": key.get(name) or "enum"}
            if name in key:
                unit["source_input_types"] = {**(unit.get("source_input_types") or {}), name: key[name]}
            else:
                # (리뷰 R1 I5) 그 번역 단위의 열거자 — 전역 표는 이름으로 묶여 같은 이름의 다른 static 것일 수 있다.
                #   덮기 전 값 집합은 카탈로그 구조 판정용으로 남긴다(리뷰 R3 W1: GLOBAL 행이 기본 영역에서 사라졌다).
                prev = (unit.get("value_domains") or {}).get(name)
                if prev:
                    unit["design_value_domains"] = {**(unit.get("design_value_domains") or {}), name: prev}
                unit["value_domains"] = {**(unit.get("value_domains") or {}), name: enum[name]}
        if not new:
            break
        unit.setdefault("design_input_vars", list(inputs))
        unit["input_vars"] = inputs + new
        record["rounds"] = _round + 1
        sequences = regenerate()
    _record_remaining(unit, sequences)
    return sequences


def _record_remaining(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> None:
    """(리뷰 R1 W2) 남은 이름은 늘 같은 정의로 — 행들이 여전히 값 없이 읽는 프로그램 객체(입력 열 밖) + 더했는데 어느 행도 값을
    주지 못한 열. MC/DC 벡터 행의 공란은 설계대로라 세지 않는다(채움 행이 그 몫). 경계 행을 붙인 뒤에도 다시 센다(리뷰 R2 I4)."""
    record = unit.get("source_read_inputs")
    if not isinstance(record, dict) or record.get("error"):
        return
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    objects = set(scope.get("globals") or {}) | set(scope.get("arrays") or {})
    now = set(unit.get("input_vars") or [])
    final = source_read_names(sequences)
    record["remaining"] = {n: r["slots"] for n, r in final.items() if n not in now and n.partition("[")[0] in objects}
    for n, added in (record.get("added") or {}).items():
        if not any(n in (q.get("inputs") or {}) for q in sequences):
            record["remaining"][n] = final.get(n, {}).get("slots", 0)
            added["no_value_in_any_row"] = True


def extended_unit_sequences(unit: Dict[str, Any]) -> List[Dict[str, Any]]:
    """(R19) 확장 프로파일의 unit 시퀀스 — 경계 행 없이 만들고 → 소스가 읽는 입력을 더해 다시 만들고 → 경계 행을 **한 번** 붙인다
    (리뷰 R1 W6: 첫 판은 경계 탐색을 두 번 했다). 입력 보완이 실패하면 그 unit 은 설계 입력 목록 그대로 만든다(선택 확장이 문서를
    잃게 하지 않는다 — R15 규칙)."""
    seqs = generate_sequences(unit, None, extended=True, boundary_rows=False)
    snapshot = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                for k in ("input_vars", "source_input_types", "value_domains", "design_input_vars", "design_value_domains")
                if (v := unit.get(k)) is not None}
    try:
        seqs = complete_source_read_inputs(
            unit, seqs, lambda: generate_sequences(unit, None, extended=True, boundary_rows=False))
    except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
        _logger.warning("SUTS 소스 읽기 입력 보완 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        for k in ("input_vars", "source_input_types", "value_domains", "design_input_vars", "design_value_domains"):
            unit.pop(k, None)
        unit.update(snapshot)
        unit["source_read_inputs"] = {"error": type(exc).__name__, "added": {}, "not_added": {}, "rounds": 0,
                                      "remaining": {}}
        seqs = generate_sequences(unit, None, extended=True, boundary_rows=False)
    seqs = append_boundary_rows(unit, seqs)
    _record_remaining(unit, seqs)
    return seqs


def input_list_gaps(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """함수가 초기값을 읽는데 시험 입력 목록에 없던 **프로그램 객체** → {"slots", "sequences", "added"}(소스 소견의 한 종류).

    확장 프로파일에선 R19 가 더한 이름 — 이 문서에선 막힌 칸이 아니므로 칸 수·행 번호는 0/빈 목록이다(처음 본 칸 수는 품질 리포트
    `source_read_inputs.slots_first_seen`, 리뷰 R1 W5) — 과 여전히 값 없이 읽는 이름, 기본 프로파일에선 문서 행의 사유에서 본
    이름이다. 지역·멤버 경로·모르는 이름은 입력 목록의 결손이 아니다."""
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    objects = set(scope.get("globals") or {}) | set(scope.get("arrays") or {})
    rec = unit.get("source_read_inputs") if isinstance(unit.get("source_read_inputs"), dict) else {}
    gaps: Dict[str, Dict[str, Any]] = {n: {"slots": 0, "sequences": [], "added": True} for n in (rec.get("added") or {})}
    # (R21 리뷰 W1) 한 행(GLOBAL)이 설정해 열로 보인 이름도, 다른 행이 값 없이 읽으면 입력 목록의 결손이다
    shown = set(((unit.get("row_io_columns") or {}).get("inputs_shown")) or [])
    inputs = set(unit.get("input_vars") or []) - shown
    for name, r in source_read_names(sequences).items():
        if name not in inputs and name not in gaps and name.partition("[")[0] in objects:
            gaps[name] = {**r, "added": False}
    return gaps


def render_row_io(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> Dict[str, Any]:
    """(R21) 행이 설정하는 입력·적는 기대값인데 TC 의 열에 없는 이름을 열로 보인다(두 프로파일).

    GLOBAL 행은 간접 전역을 최솟값으로, 입출력 없는 unit 의 호출 시퀀스는 간접 전역을 입력·기대값으로 적는데 명세 시트는
    `input_vars`·`output_vars` 열만 써서 그 값이 문서에 없었다 — oracle 은 그 숨은 입력으로 기대값을 도출했다(정본 규모 문서
    KJPDS02_PV 181 unit · 442 행 · 확정 410 칸, HDPDM01 확장 64 unit · 214 행). 첫 사용 순서로 열 뒤에 붙이고, 입력 열 상한을
    넘어 보일 수 없는 입력을 쓰는 행은 확정 칸을 `input_not_in_document:<이름>` 으로 내린다(문서에 없는 자극에 기댄 값은 확정이
    아니다). 출력은 상한을 넘으면 열로 보이지 않을 뿐(단언하지 않음) 센다. 기록은 `unit["row_io_columns"]`."""
    # (리뷰 R2 I-c) 두 번 불려도 앞의 기록을 잃지 않는다 — 앞에서 보인 이름은 이미 열이고, 여기 기록에 그대로 남는다
    prev = unit.get("row_io_columns") if isinstance(unit.get("row_io_columns"), dict) else {}
    record: Dict[str, Any] = {"inputs_shown": [], "inputs_over_cap": [], "outputs_shown": [], "outputs_over_cap": [],
                              "downgraded_slots": int(prev.get("downgraded_slots") or 0)}
    for key, field, cap in (("input", "inputs", _INPUT_COL_END - _INPUT_COL_START + 1),
                            ("output", "expected", _OUTPUT_COL_END - _OUTPUT_COL_START + 1)):
        cols = list(unit.get(f"{key}_vars") or [])
        known = set(cols)
        hidden: List[str] = []
        for seq in sequences:
            for name in (seq.get(field) or {}):
                if name not in known and name not in hidden:
                    hidden.append(name)
        room = max(0, cap - len(cols))
        if hidden[:room]:
            unit[f"{key}_vars"] = cols + hidden[:room]
        record[f"{key}s_shown"] = list(prev.get(f"{key}s_shown") or []) + hidden[:room]
        record[f"{key}s_over_cap"] = hidden[room:]
    over = set(record["inputs_over_cap"])
    for seq in sequences if over else []:
        used = [n for n in (seq.get("inputs") or {}) if n in over]
        if not used:
            continue
        reason = "input_not_in_document:" + ",".join(used[:3]) + (f"+{len(used) - 3}" if len(used) > 3 else "")
        for var, ev in (seq.get("expected_evidence") or {}).items():
            if (ev or {}).get("status") == "derived":
                # (리뷰 I1) 확정의 근거(계산 근거·가정·stub·해석한 callee)는 떼어 낸다 — 미상 칸이 근거를 말하면 안 된다
                for k in ("basis", "assumptions", "stubs", "assumed_undefined", "callees_interpreted", "callees_effects_only"):
                    ev.pop(k, None)
                ev.update(status="unknown", oracle_kind="none", reason=reason)
                seq.setdefault("expected", {})[var] = f"{VERIFY_PREFIX} {reason}"
                record["downgraded_slots"] += 1
        desc = [ln for ln in str(seq.get("description") or "").splitlines() if not ln.startswith(("Expected:", "근거: 소스 계산"))]
        if seq.get("expected"):
            desc.append("Expected: " + ", ".join(f"{v}={x}" for v, x in seq["expected"].items()))
        if any((e or {}).get("status") == "derived" for e in (seq.get("expected_evidence") or {}).values()):
            desc.append("근거: 소스 계산 (요구 적합성 미검증, 실행 미실시)")
        seq["description"] = "\n".join(desc)
    unit["row_io_columns"] = record
    return record


def summarize_row_io(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    recs = [u.get("row_io_columns") for u in units if isinstance(u.get("row_io_columns"), dict)]
    return {"units": len(recs),
            "units_with_inputs_shown": sum(1 for r in recs if r.get("inputs_shown")),
            "inputs_shown": sum(len(r.get("inputs_shown") or []) for r in recs),
            "units_with_outputs_shown": sum(1 for r in recs if r.get("outputs_shown")),
            "outputs_shown": sum(len(r.get("outputs_shown") or []) for r in recs),
            "inputs_over_cap": sum(len(r.get("inputs_over_cap") or []) for r in recs),
            "outputs_over_cap": sum(len(r.get("outputs_over_cap") or []) for r in recs),
            "downgraded_slots": sum(int(r.get("downgraded_slots") or 0) for r in recs)}


def summarize_source_read_inputs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """품질 리포트 `source_read_inputs` — 더한 unit·이름, 더하지 않은 사유 분포, 마지막 회차에 남은 이름(확장 프로파일)."""
    recs = [u.get("source_read_inputs") for u in units if isinstance(u.get("source_read_inputs"), dict)]
    not_added = Counter(why for r in recs for why in (r.get("not_added") or {}).values())
    return {"units": len(recs), "units_with_added": sum(1 for r in recs if r.get("added")),
            "names_added": sum(len(r.get("added") or {}) for r in recs),
            "slots_first_seen": sum(int(a.get("slots") or 0) for r in recs for a in (r.get("added") or {}).values()),
            "not_added": dict(sorted(not_added.items())),
            "units_input_columns_full": sum(1 for r in recs if "input_columns_full" in (r.get("not_added") or {}).values()),
            "max_rounds": max((int(r.get("rounds") or 0) for r in recs), default=0),
            "units_with_remaining": sum(1 for r in recs if r.get("remaining")),
            "names_remaining": sum(len(r.get("remaining") or {}) for r in recs),
            "errors": sum(1 for r in recs if r.get("error"))}


def attach_unit_sources(units: List[Dict[str, Any]], source_files: Optional[Dict[str, str]],
                        project_context: Optional[Dict[str, Any]] = None) -> int:
    """unit 에 정의 파일의 원문을 붙인다(`source_files` = 소스 단계의 파일당 1회 맵). 붙인 unit 수를 돌려준다.

    원문은 소스 oracle(`apply_sequence_evidence`)과 MC/DC 소스 경로의 입력이다. 맵에 없으면(잘려 읽힘·원격 미확보)
    비워 두고 사유를 남긴다 — 빈 원문을 "지원 안 되는 코드" 로 오독하지 않게 `source_unavailable_reason` 이 말한다.

    (R81) `project_context`(소스 단계 `project_context`)가 있으면 unit 마다 정의 파일의 번역 단위 범위(`project_scope` —
    typedef·매크로·열거자·전역·`#if` 상태)를 붙인다. 같은 파일의 unit 은 한 범위 객체를 공유한다(복사 없음).
    """
    attached = 0
    files = source_files or {}
    for unit in units:
        if unit.get("source_text"):
            attached += 1
            continue
        text = files.get(str(unit.get("source_path") or ""))
        if text:
            unit["source_text"], unit["source_text_complete"] = text, True
            attached += 1
        elif unit.get("source_path") and not unit.get("source_unavailable_reason"):
            unit["source_unavailable_reason"] = "source_file_not_in_source_stage"
    if project_context and (project_context.get("files") or {}):
        from generators.c_project_context import SCHEMA_VERSION, build_scopes
        if project_context.get("schema_version") != SCHEMA_VERSION:
            # 옛 모양의 문맥(캐시)으로 범위를 만들면 조용히 틀린 판정을 낸다 — 붙이지 않는다(MC/DC 는 범위 없는 경로로 간다).
            for unit in units:
                unit.setdefault("project_context_status", f"schema_mismatch:{project_context.get('schema_version')}")
            return attached
        paths = [str(u.get("source_path") or "") for u in units if u.get("source_text")]
        scopes = build_scopes(project_context, [p for p in paths if p in project_context["files"]])
        for unit in units:
            scope = scopes.get(str(unit.get("source_path") or ""))
            if scope is not None and unit.get("source_text"):
                unit["project_scope"] = scope
    return attached


def _mcdc_declared_domains(input_vars: List[str], type_of: Any, value_domains: Dict[str, Any],
                           declared: Any, is_pointer: Any = None,
                           parameter_names: Optional[set] = None) -> Dict[str, Dict[str, Any]]:
    """MC/DC 탐색 도메인 — **선언**이 정한 정수 도메인만(이름 패턴·기본값 추측 제외).

    선언 타입(파라미터·전역 선언 → `_TYPE_ALIASES` 로 폭이 정의된 이름)은 타입 전폭, enum 은 열거자 값 집합이다.
    설계 범위(SwUDS Value Range)는 엔진이 **선언 도메인 안에서만** 좁힌다(`build_mcdc_design`) — 여기서 넓히지 않는다.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for v in input_vars:
        if is_pointer is not None and is_pointer(v):
            # (리뷰 W2) 포인터·배열의 SUTS 값은 **가리키는 대상**의 값이다. `if (pv)` 의 진리값은 주소라 그 값으로
            # 쌍을 만들면 실행 시 두 행 모두 참인 가짜 쌍이 된다 — 도메인을 주지 않는다(결정은 unsupported 로 남는다).
            continue
        origin = "parameter" if parameter_names and v in parameter_names else "global"
        t = type_of(v)
        if t == _ENUM_TYPE:
            raw = (value_domains.get(v) or {}).get("values") or []
            values = sorted({int(x) for x in raw if isinstance(x, int) and not isinstance(x, bool)})
            if values:
                out[v] = {"min": values[0], "max": values[-1], "values": values, "type": "enum",
                          "source": "enum_declaration", "origin": origin}
            continue
        if t in ("float", _UNKNOWN_TYPE, _RANGE_TYPE, "") or t not in _TYPE_BOUNDARIES or not declared(v):
            continue
        tb = _TYPE_BOUNDARIES[t]
        out[v] = {"min": int(tb["min"]), "max": int(tb["max"]), "type": t, "source": "declared_type", "origin": origin}
    return out


def summarize_mcdc_design(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """MC/DC **설계** 집계(품질 리포트용) — 실행 커버리지가 아니다. 쌍을 못 만든 결정도 분모에 남고 사유별로 센다.

    `retained_pairs` 는 행 상한 뒤에도 두 행이 모두 남은 쌍, `truncated_pairs` 는 상한에 잘린 쌍이다(침묵 절단 금지).
    """
    out: Dict[str, Any] = {"units": 0, "decisions": 0, "conditions": 0, "designed": 0, "partial": 0,
                           "no_pair_found": 0, "unsupported": 0, "conditions_paired": 0, "retained_pairs": 0,
                           "truncated_pairs": 0, "invalidated_pairs": 0, "unsupported_reasons": {},
                           "unenumerated_functions": 0, "unenumerated_reasons": {}, "design_range_conflicts": [],
                           # (R81) 결정이 읽지 않는 입력의 도메인을 몰라 벡터가 비워 둔 결정(행은 그 칸이 공란)
                           "decisions_with_blank_inputs": 0,
                           # (R81 리뷰 I5) 쌍이 없음을 **증명**한 결정(강결합 동일 조건·상수 결정) — 탐색 실패와 분리
                           "proven_infeasible": 0,
                           "execution_status": "not_run", "reachability": "unverified"}
    out["units_not_analyzed"] = 0
    for unit in units:
        report = unit.get("mcdc_design")
        if not report:
            # 입출력이 없어 전략 목록을 쓰지 않는 unit(조기 반환) — 분석 안 한 것이지 결정이 없는 것이 아니다.
            out["units_not_analyzed"] += 1
            continue
        out["units"] += 1
        for name, dom in (report.get("domains") or {}).items():
            if dom.get("design_range_conflict"):
                # 설계 범위가 선언 타입/열거자와 안 맞아 MC/DC 는 **선언** 도메인을 썼다 — BV 행과 도메인이 갈릴 수 있다.
                out["design_range_conflicts"].append(f"{report.get('function', '')}.{name}")
        for d in report.get("decisions") or []:
            if d.get("status") == "unenumerated":
                out["unenumerated_functions"] += 1
                reason = str(d.get("reason") or "unknown").split(":", 1)[0]
                out["unenumerated_reasons"][reason] = out["unenumerated_reasons"].get(reason, 0) + 1
                continue
            out["decisions"] += 1
            out["decisions_with_blank_inputs"] += bool(d.get("inputs_not_designed"))
            out["proven_infeasible"] += str(d.get("reason") or "").startswith("unique_cause_infeasible:")
            out["conditions"] += len(d.get("conditions") or [])
            status = d.get("status", "unsupported")
            out[status if status in ("designed", "partial", "no_pair_found") else "unsupported"] += 1
            if d.get("evaluation") == "source_path" or d.get("path_refusal"):
                # (R2c 리뷰 I3) 함수 실행 모델로 다시 본 결정(설계했든 거부했든) — 식 엔진 거부 사유 분포를 잃지 않는다
                path = out.setdefault("source_path", {"decisions": 0, "designed": 0, "refused": 0, "static_reasons": {}})
                path["decisions"] += 1
                path["designed"] += status == "designed"
                path["refused"] += bool(d.get("path_refusal"))
                why = str(d.get("static_reason") or "unknown").split(":", 1)[0]
                path["static_reasons"][why] = path["static_reasons"].get(why, 0) + 1
            if status == "unsupported":
                # ``path_evaluation:<state>`` 은 상태까지 — 하나로 뭉치면 사유가 사라진다
                parts = str(d.get("reason") or "unknown").split(":")
                reason = ":".join(parts[:2]) if parts[0] in ("path_evaluation", "path_refused") else parts[0]
                out["unsupported_reasons"][reason] = out["unsupported_reasons"].get(reason, 0) + 1
            for pair in d.get("pairs") or []:
                out["conditions_paired"] += 1
                key = {"retained": "retained_pairs", "invalidated": "invalidated_pairs"}.get(
                    pair.get("retained_status"), "truncated_pairs")
                out[key] += 1
    return out


def _summarize_source_findings(units: List[Dict[str, Any]], all_sequences: Dict[str, List[Dict[str, Any]]]):
    from generators import source_findings as sf
    out = sf.summarize_findings(sf.collect_findings(units, all_sequences, {}))
    # (R19) 입력 목록 밖 읽기는 미정의 동작 소견과 따로 센다(`findings` 는 그대로 UB 소견 수)
    gaps = sf.collect_input_gap_findings(units, _input_list_gaps(units, all_sequences), {})
    out["input_list_gaps"] = sf.summarize_input_gaps(gaps)
    return out


def _input_list_gaps(units: List[Dict[str, Any]], all_sequences: Dict[str, List[Dict[str, Any]]]
                     ) -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {u["fid"]: input_list_gaps(u, all_sequences.get(u["fid"]) or []) for u in units}


def _mcdc_vector_key(inputs: Dict[str, Any]) -> str:
    return json.dumps(inputs, sort_keys=True)


def _mcdc_vector_roles(report: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """입력 벡터 → 그 벡터가 구성원인 (결정, 조건, 역할, 진리값, 결정값) 목록."""
    roles: Dict[str, List[Dict[str, Any]]] = {}
    for decision in report.get("decisions") or []:
        for pair in decision.get("pairs") or []:
            for side in ("a", "b"):
                roles.setdefault(_mcdc_vector_key(pair[f"inputs_{side}"]), []).append({
                    "decision_id": decision["decision_id"], "condition_id": pair["condition_id"], "role": side.upper(),
                    "truth": pair[f"truth_{side}"], "decision": pair[f"decision_{side}"], "pair": pair})
    return roles


def _mcdc_vector_label(retained: List[Dict[str, Any]], lost_statuses: Optional[List[str]] = None) -> str:
    """행 라벨. `retained` = finalize 가 그 행에 붙인 **살아남은** 쌍 구성 기록(`seq["mcdc_design"]`).

    `lost_statuses` = 이 벡터가 구성원인 쌍들의 finalize 결과 — 살아남은 쌍이 없을 때 **왜** 없는지(절단/재검증 탈락)를 적는다.
    """
    if not retained:
        lost = [s for s in (lost_statuses or []) if s != "retained"]
        if lost:
            cause = " · ".join(f"{label} {lost.count(key)}건" for key, label in
                               (("truncated", "짝 행 상한 절단"), ("invalidated", "재검증 탈락")) if lost.count(key))
            return f"MC/DC 설계 벡터 — 독립 영향 쌍 미성립({cause}, MCDC Design 시트 참조)"
        return "MC/DC 설계 벡터"
    parts = []
    for r in retained:
        truth = _mcdc_truth_text(r["truth"], r.get("observed"))
        parts.append(f"{r['decision_id']}:{r['condition_id']}({r['role'].upper()}) 조건[{truth}]→결정 {'T' if r['decision'] else 'F'}")
    # (R2c) 함수 실행 모델로 설계한 쌍은 "식 평가" 가 아니다 — 모델상 도달했을 뿐 실행 도달성은 여전히 미검증
    kinds = {r.get("evaluation") or "expression" for r in retained}
    basis = "함수 실행 모델 설계" if kinds == {"source_path"} else "식 평가 설계" if kinds == {"expression"} else "식 평가·함수 실행 모델 설계"
    ub = sorted({k for r in retained for k in r.get("possible_ub") or []})
    tail = f" · 결정 이후 가능 UB: {'+'.join(ub)}" if ub else ""
    return "MC/DC 독립 영향 쌍: " + ", ".join(parts) + f" ({basis}, 도달성 미검증·미실행{tail})"


def _mcdc_truth_text(values: Any, observed: Any = None) -> str:
    """조건 진리값 표기 — 단락 평가로 **평가되지 않은** 조건은 ``-``(don't-care), 입력이 정하지 못한 값도 ``-``.

    (R2c 리뷰 W1) 평가되지 않은 조건을 복사본에서 계산한 T/F 로 적으면 unique-cause 쌍이 두 조건을 뒤집은 것처럼 보인다.
    """
    marks = []
    for i, v in enumerate(values or []):
        evaluated = observed is None or (i < len(observed) and observed[i])
        marks.append("-" if v is None or not evaluated else ("T" if v else "F"))
    return "".join(marks)


def _format_test_value(value: Any, typename: str) -> Any:
    """Format test values to match reference document patterns.

    - bit/bool: use hex (0x0, 0x1)
    - REG/hardware: use hex for small ints
    - others: plain integer
    """
    if value is None:
        return 0
    if isinstance(value, float) and value == int(value):
        value = int(value)
    if typename in ("bit", "bool"):
        if isinstance(value, (int, float)):
            iv = int(value)
            if 0 <= iv <= 0xFF:
                return f"0x{iv:X}"
    return value


def _infer_expected_for_strategy(
    bounds: Dict[str, Any],
    strategy_key: str,
    typename: str,
    logic_flow: List[Dict[str, Any]],
    var_name: str,
) -> Any:
    """Infer expected output value based on input strategy and logic analysis.

    Uses logic_flow branch analysis to determine more accurate expected outputs:
    - Error-boundary inputs (min_inv/max_inv): saturation, clamping, or error flag
    - Valid boundary inputs (min/max): the boundary value itself (pass-through or capped)
    - Mid-range inputs: normal processing result
    """
    is_bit = typename in ("bit", "bool")
    has_guard = _flow_has_guard_clause(logic_flow, var_name)
    has_clamp = _flow_has_clamp_pattern(logic_flow, var_name)
    is_enable_flag = _is_enable_disable_var(var_name)
    is_counter = _is_counter_accumulator_var(var_name)
    is_state_var = _is_state_machine_var(var_name)
    bmin = bounds.get("min", 0)
    bmax = bounds.get("max", 0)
    bmid = bounds.get("mid", 0)
    # Pre-compute type normalization once (used by min_inv/max_inv fallback)
    _normalized = typename.lower().replace(" ", "").replace("_t", "")
    _is_known_type = _normalized in _KNOWN_SATURATE_TYPES

    # Enable/disable flag: output toggles between 0/1 on valid input
    if is_enable_flag and strategy_key in ("min", "BV_MIN"):
        return 0
    if is_enable_flag and strategy_key in ("max", "BV_MAX"):
        return 1

    # Counter/accumulator: mid-range or clamp at max on overflow
    if is_counter:
        if strategy_key == "max_inv":
            return bmax  # saturates/wraps at max
        if strategy_key == "min_inv":
            return bmin  # saturates at min

    # State machine variable: invalid input → stays in safe/init state
    if is_state_var and strategy_key in ("min_inv", "max_inv"):
        return bmin  # remain in initial/safe state on invalid transition

    if strategy_key == "min_inv":
        if is_bit:
            return bmax
        if has_clamp:
            return bmin   # clamped to lower bound
        if has_guard:
            return bmin   # guarded: stays at safe min value
        if _is_known_type:
            return bmin   # type-inferred saturation to lower bound
        raw = bounds.get("min_inv", bmin)
        return f"{_VERIFY_NEEDED_PREFIX} {raw}"

    if strategy_key == "max_inv":
        if is_bit:
            return bmax
        if has_clamp:
            return bmax   # clamped to upper bound
        if has_guard:
            return bmax   # guarded: stays at safe max value
        if _is_known_type:
            return bmax   # type-inferred saturation to upper bound
        raw = bounds.get("max_inv", bmax)
        return f"{_VERIFY_NEEDED_PREFIX} {raw}"

    if strategy_key == "min":
        if is_bit:
            return 0
        return bmin

    if strategy_key == "max":
        return bmax

    return bmid


def _is_enable_disable_var(var_name: str) -> bool:
    """Check if variable name indicates an enable/disable flag or activation signal."""
    name = var_name.lower()
    keywords = ("enable", "disable", "active", "flag", "en_", "_en", "on_", "_on",
                 "inhibit", "valid", "allowed", "permit")
    return any(kw in name for kw in keywords)


def _is_counter_accumulator_var(var_name: str) -> bool:
    """Check if variable name indicates a counter or accumulator."""
    name = var_name.lower()
    keywords = ("count", "cnt", "accum", "sum", "total", "index", "idx",
                 "tick", "timer", "elapsed", "delta")
    return any(kw in name for kw in keywords)


def _is_state_machine_var(var_name: str) -> bool:
    """Check if variable name indicates a state machine variable."""
    name = var_name.lower()
    keywords = ("state", "_st_", "_sts", "status", "mode", "phase", "stage",
                 "step", "fsm", "_sm_")
    return any(kw in name for kw in keywords)


def _extract_switch_cases(
    logic_flow: List[Dict[str, Any]],
    input_vars: List[str],
) -> List[Tuple[str, Any, str]]:
    """Extract switch-case values from logic_flow for branch coverage.

    Returns list of (variable_name, case_value, case_label) tuples.
    """
    cases: List[Tuple[str, Any, str]] = []
    for node in logic_flow:
        ntype = str(node.get("type", "")).lower()
        # switch-case nodes
        if ntype == "switch":
            sw_var = str(node.get("variable", "") or node.get("condition", "")).strip()
            # Match to input_vars
            matched_var = ""
            for iv in input_vars:
                if iv.lower() in sw_var.lower() or sw_var.lower() in iv.lower():
                    matched_var = iv
                    break
            if not matched_var and input_vars:
                matched_var = input_vars[0]
            for child in node.get("children", []) or node.get("cases", []):
                case_val = child.get("value")
                if case_val is None:
                    case_val = child.get("case")
                case_label = str(child.get("label", "") or child.get("text", "") or f"case_{case_val}")
                if case_val is not None:
                    cases.append((matched_var, case_val, case_label))
        # if-else chains that look like enum comparisons (e.g., "var == ENUM_VAL")
        elif ntype == "if":
            cond = str(node.get("condition", "")).strip()
            for iv in input_vars:
                if iv.lower() in cond.lower() and "==" in cond:
                    # Extract the compared value
                    parts = cond.split("==")
                    if len(parts) == 2:
                        val_str = parts[1].strip().strip("() ")
                        try:
                            val = int(val_str, 0)  # supports 0x hex
                            cases.append((iv, val, f"조건 {iv}=={val_str}"))
                        except ValueError:
                            pass  # Skip enum names — can't use as numeric test input
        # Recurse into children (for non-switch nodes only)
        if ntype != "switch":
            for child in node.get("children", []):
                cases.extend(_extract_switch_cases([child], input_vars))
    # Deduplicate by (var, val)
    seen = set()
    unique: List[Tuple[str, Any, str]] = []
    for c in cases:
        key = (c[0], str(c[1]))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def _flow_has_guard_clause(logic_flow: List[Dict[str, Any]], var_name: str) -> bool:
    """Check if logic_flow contains an if-guard referencing var_name (range check)."""
    clean = var_name.lower().strip()
    for node in logic_flow:
        cond = str(node.get("condition", "") or node.get("text", "")).lower()
        if clean in cond:
            for kw in ("<", ">", "<=", ">=", "==", "!=", "min", "max", "limit"):
                if kw in cond:
                    return True
        for child in node.get("children", []):
            if _flow_has_guard_clause([child], var_name):
                return True
    return False


def _flow_has_clamp_pattern(logic_flow: List[Dict[str, Any]], var_name: str) -> bool:
    """Check if logic_flow contains a clamp/saturation pattern for var_name."""
    clean = var_name.lower().strip()
    for node in logic_flow:
        text = str(node.get("text", "") or node.get("condition", "")).lower()
        if clean in text:
            for kw in ("clamp", "saturate", "limit", "cap", "bound", "clip"):
                if kw in text:
                    return True
            if ("=" in text) and any(w in text for w in ("max", "min", "0xff", "0xffff")):
                return True
        for child in node.get("children", []):
            if _flow_has_clamp_pattern([child], var_name):
                return True
    return False


# ---------------------------------------------------------------------------
# Phase 4: AI Enhancement (optional)
# ---------------------------------------------------------------------------

_SUTS_AI_SYSTEM_PROMPT = (
    "You are a software unit test engineer writing SUTS for automotive ECU software (ISO 26262).\n"
    "Given a C function context and test sequences, provide accurate expected output values.\n"
    "Rules:\n"
    "- Analyze the function name, description, calls, and logic conditions to infer behavior.\n"
    "- For void/no-param functions: use 'Indirect variables' as testable state variables.\n"
    "  NORMAL_CALL: expected = typical post-call values (e.g., initialized/reset state).\n"
    "  ERROR_PATH: expected = safe/default state after error (0 or initial value).\n"
    "  REPEAT_CALL: expected = same stable state (idempotent).\n"
    "- For functions with inputs: boundary-exceeding inputs → clamped/saturated expected output.\n"
    "- Return ONLY a JSON array: [{\"seq_num\":1, \"expected\":{\"var\":value,...}}, ...]\n"
    "- Only set expected values for variables that appear in 'Indirect variables' or 'Output variables'.\n"
    "- Values must be numeric (int or float). Use 0 for unknown/safe defaults."
)


_AI_TIMEOUT_SEC = 30
_AI_MAX_RETRIES = 2


def _ai_call_with_retry(agent_call_fn, ai_config, messages, *,
                         stage: str, max_retries: int = _AI_MAX_RETRIES,
                         timeout: int = _AI_TIMEOUT_SEC,
                         temperature: float = 0.2) -> str:
    """Wrapper around agent_call with timeout and retry logic."""
    import threading

    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        result_holder: Dict[str, Any] = {}
        exc_holder: List[Exception] = []

        def _invoke():
            try:
                r = agent_call_fn(
                    ai_config, messages,
                    role="writer", stage=stage,
                    settings={"temperature": temperature},
                )
                result_holder["val"] = r
            except Exception as ex:
                exc_holder.append(ex)

        t = threading.Thread(target=_invoke, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            _logger.warning("AI call timed out (attempt %d/%d, %ds)", attempt, max_retries, timeout)
            last_err = TimeoutError(f"AI call timed out after {timeout}s")
            continue

        if exc_holder:
            last_err = exc_holder[0]
            _logger.warning("AI call error (attempt %d/%d): %s", attempt, max_retries, last_err)
            continue

        raw = result_holder.get("val")
        reply = raw.get("output", "") if isinstance(raw, dict) else ""
        if reply:
            return reply
        _logger.warning("AI returned empty response (attempt %d/%d)", attempt, max_retries)
        last_err = ValueError("Empty AI response")

    if last_err:
        _logger.warning("AI call exhausted retries: %s", last_err)
    return ""


def _parse_ai_json(reply: str, expect_list: bool = True) -> Any:
    """Parse AI response as JSON with fallback regex extraction."""
    import json as _json
    if not reply:
        return None
    try:
        payload = _json.loads(reply) if isinstance(reply, str) else reply
        if expect_list and isinstance(payload, list):
            return payload
        if not expect_list and isinstance(payload, dict):
            return payload
        return payload
    except Exception:
        pattern = r"\[[\s\S]*\]" if expect_list else r"\{[\s\S]*\}"
        m = re.search(pattern, reply)
        if m:
            try:
                return _json.loads(m.group())
            except Exception:
                pass
    return None


def _validate_ai_sequence_item(item: Any, valid_seq_nums: set) -> bool:
    """Validate a single AI-enhanced sequence item."""
    if not isinstance(item, dict):
        return False
    if "seq_num" not in item or "expected" not in item:
        return False
    if item["seq_num"] not in valid_seq_nums:
        return False
    if not isinstance(item["expected"], dict):
        return False
    return True


def enhance_sequences_with_ai(
    unit: Dict[str, Any],
    sequences: List[Dict[str, Any]],
    ai_config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Enhance expected output values using AI with timeout and retry."""
    if not ai_config:
        return sequences

    try:
        from workflow.ai import agent_call
    except ImportError:
        _logger.warning("workflow.ai not available; skipping AI enhancement")
        return sequences

    _inp_vars = unit.get("input_vars") or []
    _out_vars = unit.get("output_vars") or []
    _indirect = unit.get("indirect_vars") or []
    _calls = unit.get("calls_list") or []
    _lf = unit.get("logic_flow") or []

    # Summarise logic_flow conditions for AI context
    _cond_lines: List[str] = []
    def _collect_conds(nodes: List[Any], depth: int = 0) -> None:
        for _n in nodes:
            if not isinstance(_n, dict):
                continue
            _c = str(_n.get("condition") or _n.get("text") or "").strip()
            if _c and depth < 3:
                _cond_lines.append(_c[:100])
            for _key in ("true_body", "false_body", "body"):
                _sub = _n.get(_key)
                if isinstance(_sub, list):
                    _collect_conds(_sub, depth + 1)
    _collect_conds(_lf)

    func_ctx = (
        f"Function: {unit.get('prototype', '')}\n"
        f"Description: {unit.get('description', '')}\n"
        f"Input variables: {_inp_vars}\n"
        f"Output variables: {_out_vars}\n"
        f"Calls: {_calls[:8]}\n"
    )
    if _indirect:
        func_ctx += f"Indirect variables (from callees): {_indirect}\n"
    if _cond_lines:
        func_ctx += f"Logic conditions: {_cond_lines[:6]}\n"

    seq_info = "Current sequences:\n"
    for s in sequences:
        seq_info += f"  Seq {s['seq_num']} ({s['strategy']}): inputs={s['inputs']}, expected={s['expected']}\n"

    reply = _ai_call_with_retry(
        agent_call, ai_config,
        [
            {"role": "system", "content": _SUTS_AI_SYSTEM_PROMPT},
            {"role": "user", "content": func_ctx + "\n" + seq_info},
        ],
        stage="suts_enhance",
        temperature=0.2,
    )

    payload = _parse_ai_json(reply, expect_list=True)
    if isinstance(payload, list):
        valid_nums = {s["seq_num"] for s in sequences}
        seq_map = {s["seq_num"]: s for s in sequences}
        applied = 0
        for item in payload:
            if _validate_ai_sequence_item(item, valid_nums):
                allowed = set(_out_vars) | set(_indirect) | set(seq_map[item["seq_num"]].get("expected") or {})
                seq_map[item["seq_num"]].setdefault("ai_expected_candidates", {}).update({
                    key: value for key, value in item["expected"].items() if key in allowed})
                applied += 1
        if applied:
            _logger.info("AI enhanced %d/%d sequences for %s", applied, len(payload), unit.get("name"))

    return apply_sequence_evidence(unit, sequences)


# ---------------------------------------------------------------------------
# Phase 5: XLSM output
# ---------------------------------------------------------------------------

def generate_suts_xlsm(
    template_path: Optional[str],
    units: List[Dict[str, Any]],
    all_sequences: Dict[str, List[Dict[str, Any]]],
    output_path: str,
    project_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate SUTS XLSM file."""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        _logger.error("openpyxl not installed")
        raise

    cfg = project_config or {}
    project_id = cfg.get("project_id", "PROJECT")
    doc_id = cfg.get("doc_id", f"{project_id}-SUTS")
    version = cfg.get("version", "v1.00")
    asil_level = cfg.get("asil_level", "")

    if template_path and Path(template_path).is_file():
        wb = openpyxl.load_workbook(template_path, keep_vba=True)
        _logger.info("Loaded SUTS template: %s", template_path)
    else:
        wb = openpyxl.Workbook()
        _create_suts_cover(wb, project_id, doc_id, version, asil_level)
        _create_suts_history(wb, version)
        _create_suts_intro(wb)
        _create_suts_test_env(wb)
        _logger.info("Created new SUTS workbook (no template)")

    thin = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    hdr_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    hdr_font = Font(name="맑은 고딕", size=9, bold=True)
    data_font = Font(name="맑은 고딕", size=8)
    wrap = Alignment(wrap_text=True, vertical="top")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # 정본을 템플릿으로 쓰면 **과거 개정 이력이 그대로 딸려온다**. 지우지 않고
    # 다음 행에 이번 개정을 덧붙인다(사용자 결정, 2026-08-12) — 그게 개정 이력의
    # 본래 쓰임이고, 지우면 문서가 어디서 왔는지 사라진다.
    from generators.history_row import append_history_row
    append_history_row(wb, version=version, description=str(cfg.get("history_note") or ""))

    sheet_name = "2.SW Unit Test Spec"
    if sheet_name in wb.sheetnames:
        del wb[sheet_name]
    ws = wb.create_sheet(sheet_name)

    # --- Title row (row 1, merged A1 to last column — matches reference A1:EG1) ---
    title_font = Font(name="맑은 고딕", size=13, bold=True)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=_RELATED_COL)
    ws.cell(row=1, column=1, value="Software Unit Test Specification").font = title_font
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    # --- Header rows (5-6) ---
    # Row 5: group headers — merged spans
    def _fill_and_merge(row, c_start, c_end, label):
        for c in range(c_start, c_end + 1):
            ws.cell(row=row, column=c).fill = hdr_fill
            ws.cell(row=row, column=c).border = thin
            ws.cell(row=row, column=c).alignment = center
        ws.cell(row=row, column=c_start, value=label).font = hdr_font
        if c_end > c_start:
            try:
                ws.merge_cells(
                    start_row=row, start_column=c_start,
                    end_row=row, end_column=c_end,
                )
            except Exception:
                pass

    # 밴드 행 — 정본 실측: B3:G3 · H3:CZ3 · DA3:GF3 · GG3
    # ⚠ 'Input' 밴드는 시퀀스 번호 열(H)부터 시작한다. 정본 그대로다.
    _fill_and_merge(_BAND_ROW, _COL_INDEX, _COL_GEN, "Test Case")
    _fill_and_merge(_BAND_ROW, _SEQ_COL, _INPUT_COL_END, "Input")
    _fill_and_merge(_BAND_ROW, _OUTPUT_COL_START, _OUTPUT_COL_END, "Expected Result")
    _fill_and_merge(_BAND_ROW, _RELATED_COL, _RELATED_COL, "Related ID")
    ws.row_dimensions[_BAND_ROW].height = 18

    # 헤더 행 — 정의는 모듈 상수 `_FIXED_HEADERS`(단일 출처).
    for c, h in _FIXED_HEADERS.items():
        cell = ws.cell(row=_HEADER_ROW, column=c, value=h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.border = thin
        cell.alignment = center

    ws.cell(row=_HEADER_ROW, column=_RELATED_COL, value=_RELATED_HEADER).font = hdr_font
    ws.cell(row=_HEADER_ROW, column=_RELATED_COL).fill = hdr_fill
    ws.cell(row=_HEADER_ROW, column=_RELATED_COL).border = thin
    ws.cell(row=_HEADER_ROW, column=_RELATED_COL).alignment = center

    # Inpt[n] / ExpR[n] 슬롯 라벨 — 정본은 헤더 행에 이 이름을 둔다(변수명은 TC 행).
    for idx, col in enumerate(range(_INPUT_COL_START, _INPUT_COL_END + 1)):
        cell = ws.cell(row=_HEADER_ROW, column=col, value=f"Inpt[{idx}]")
        cell.font, cell.fill, cell.border, cell.alignment = hdr_font, hdr_fill, thin, center
    for idx, col in enumerate(range(_OUTPUT_COL_START, _OUTPUT_COL_END + 1)):
        cell = ws.cell(row=_HEADER_ROW, column=col, value=f"ExpR[{idx}]")
        cell.font, cell.fill, cell.border, cell.alignment = hdr_font, hdr_fill, thin, center
    ws.row_dimensions[_HEADER_ROW].height = 34.5

    # Column widths — 정본 기준(고정 열만; Inpt/ExpR 는 변수명 길이로 아래에서 잡는다)
    ws.column_dimensions["B"].width = 7       # Index
    ws.column_dimensions["C"].width = 24      # TC_ID
    ws.column_dimensions["D"].width = 34      # Unit
    ws.column_dimensions["E"].width = 9       # Safety Related
    ws.column_dimensions["F"].width = 11      # Test Method
    ws.column_dimensions["G"].width = 14      # TC Generation Method
    ws.column_dimensions["H"].width = 5       # 시퀀스 번호
    ws.column_dimensions[get_column_letter(_RELATED_COL)].width = 16  # SUDS

    # --- Data rows ---
    row_num = _DATA_START_ROW
    tc_count = 0
    total_seq = 0
    rendered_tc_ids: Dict[str, str] = {}

    for unit in units:
        fid = unit["fid"]
        seqs = all_sequences.get(fid, [])
        if not seqs:
            seqs = [{"seq_num": 1, "inputs": {}, "expected": {}, "strategy": "N/A"}]

        # SUDS(설계 ID) — 확보하지 못하면 **빈칸**으로 둔다.
        # ⚠ 이전 판은 `fid`(= 소스 파싱 순번 `SwUFn_{n:04d}`)를 그대로 적었다. 그건
        #   SwUDS 가 부여한 설계 ID 가 아니라 이 실행에서 만든 번호라, 모양만 맞고
        #   **다른 설계 요소를 가리킨다**(정본과 교집합 178/251 — 나머지는 오조준).
        #   틀린 ID 가 추적성으로 보이는 것이 빈칸보다 나쁘다.
        suds_id = str(unit.get("suds_id") or unit.get("design_id") or "").strip()
        # 정본은 `TC_ID = "SwUTC_" + SUDS`(1,013/1,014). 설계 ID 를 확보한 경우에만
        # 그 규칙을 따르고, 못 찾았으면 종전대로 내부 fid 로 만든다 — TC_ID 는 시트의
        # 키라 비울 수 없기 때문이다(비우면 행을 식별할 수 없다).
        tc_id = f"SwUTC_{suds_id or fid}"
        rendered_tc_ids[fid] = tc_id
        start_row = row_num

        # TC 정의 행 — 정본에서 이 행은 **변수명 행**이다. 시퀀스 번호·Test Method·
        # TC Gen Method 는 여기 쓰지 않는다(아래 시퀀스 그룹에서 쓴다).
        ws.cell(row=row_num, column=_COL_INDEX, value=tc_count + 1).font = data_font
        ws.cell(row=row_num, column=_COL_INDEX).alignment = center
        ws.cell(row=row_num, column=_COL_TC_ID, value=tc_id).font = data_font
        ws.cell(row=row_num, column=_COL_UNIT, value=unit["name"]).font = data_font
        ws.cell(row=row_num, column=_COL_SAFETY,
                value=resolve_safety_related(unit.get("asil"))).font = data_font
        ws.cell(row=row_num, column=_COL_SAFETY).alignment = center
        if suds_id:
            ws.cell(row=row_num, column=_RELATED_COL, value=suds_id).font = data_font
            ws.cell(row=row_num, column=_RELATED_COL).alignment = center

        # Input variable names in TC row
        input_vars = unit.get("input_vars", [])
        for vi, vname in enumerate(input_vars):
            col = _INPUT_COL_START + vi
            if col > _INPUT_COL_END:
                break
            cell = ws.cell(row=row_num, column=col, value=vname)
            cell.font = hdr_font
            cell.alignment = center
            ws.column_dimensions[get_column_letter(col)].width = max(
                12, min(len(vname) + 2, 24)
            )

        # Output variable names in TC row
        output_vars = unit.get("output_vars", [])
        for vi, vname in enumerate(output_vars):
            col = _OUTPUT_COL_START + vi
            if col > _OUTPUT_COL_END:
                break
            cell = ws.cell(row=row_num, column=col, value=vname)
            cell.font = hdr_font
            cell.alignment = center
            ws.column_dimensions[get_column_letter(col)].width = max(
                12, min(len(vname) + 2, 24)
            )

        # Apply borders to TC row
        max_data_col = max(
            12,
            _INPUT_COL_START + len(input_vars) - 1,
            _OUTPUT_COL_START + len(output_vars) - 1,
            _RELATED_COL,
        )
        for c in range(2, max_data_col + 1):
            ws.cell(row=row_num, column=c).border = thin
            ws.cell(row=row_num, column=c).alignment = wrap

        row_num += 1

        # 시퀀스 행 — Test Method / TC Gen Method 는 **연속된 같은 값끼리 묶어** 쓴다.
        # 정본이 그렇게 돼 있다(첫 TC: seq 1~3 = REQ, 4~7 = FI 로 F열이 두 번 병합).
        # 값이 바뀌는 지점에서만 쓰고, 아래 `_seq_groups` 로 병합한다.
        _seq_groups: List[Tuple[int, int, str, str]] = []   # (start_row, end_row, method, gen)
        for seq in seqs:
            ws.cell(row=row_num, column=_SEQ_COL, value=seq["seq_num"]).font = data_font
            ws.cell(row=row_num, column=_SEQ_COL).alignment = center
            ws.cell(row=row_num, column=_SEQ_COL).border = thin

            strategy_val = str(seq.get("strategy", "") or "")
            s_method = resolve_seq_test_method(strategy_val)
            s_gen = resolve_seq_gen_method(strategy_val)
            if _seq_groups and _seq_groups[-1][2] == s_method and _seq_groups[-1][3] == s_gen:
                g = _seq_groups[-1]
                _seq_groups[-1] = (g[0], row_num, g[2], g[3])
            else:
                _seq_groups.append((row_num, row_num, s_method, s_gen))

            # Input values
            for vi, vname in enumerate(input_vars):
                col = _INPUT_COL_START + vi
                if col > _INPUT_COL_END:
                    break
                val = seq.get("inputs", {}).get(vname)
                if val is not None:
                    cell = ws.cell(row=row_num, column=col, value=val)
                    cell.font = data_font
                    cell.alignment = center
                    cell.border = thin

            # Expected output values
            for vi, vname in enumerate(output_vars):
                col = _OUTPUT_COL_START + vi
                if col > _OUTPUT_COL_END:
                    break
                val = seq.get("expected", {}).get(vname)
                if val is not None:
                    cell = ws.cell(row=row_num, column=col, value=val)
                    cell.font = data_font
                    cell.alignment = center
                    cell.border = thin

            row_num += 1
            total_seq += 1

        # Test Method / TC Gen Method — 그룹의 첫 행에 쓰고 그룹 범위로 병합한다.
        for g_start, g_end, g_method, g_gen in _seq_groups:
            for col, val in ((_COL_METHOD, g_method), (_COL_GEN, g_gen)):
                cell = ws.cell(row=g_start, column=col, value=val)
                cell.font = data_font
                cell.alignment = center
                cell.border = thin
                if g_end > g_start:
                    try:
                        # (R76 N103) 새로 만든 시트의 순차 블록 — 포함 검사(O(기존 병합 수)) 없는 경로(`_xlsx_merge`).
                        merge_fresh(ws, g_start, col, g_end, col)
                    except Exception as exc:  # noqa: BLE001
                        _logger.debug("seq group merge skipped (%s%d:%d): %s",
                                      get_column_letter(col), g_start, g_end, exc)

        # TC 메타 열은 블록 전체 병합 — 정본과 같다(B/C/D/E/GG 가 5:12 처럼 덮인다).
        # ⚠ Test Method(F)·TC Gen Method(G)는 **제외**한다. 시퀀스 그룹 단위라
        #   블록 전체로 병합하면 REQ/FI 구분이 사라진다.
        end_row = row_num - 1
        tc_def_row = start_row
        merge_cols = [_COL_INDEX, _COL_TC_ID, _COL_UNIT, _COL_SAFETY, _RELATED_COL]
        if end_row > tc_def_row:
            for mc in merge_cols:
                try:
                    merge_fresh(ws, tc_def_row, mc, end_row, mc)
                except Exception as exc:  # noqa: BLE001
                    _logger.debug("TC meta merge skipped (col %d, %d:%d): %s",
                                  mc, tc_def_row, end_row, exc)

        tc_count += 1

    _logger.info("Wrote %d TCs, %d sequences to sheet", tc_count, total_seq)

    # --- Traceability sheet: Component → Function → TC ---
    _write_suts_traceability_sheet(wb, units, thin, hdr_fill, hdr_font, data_font)
    # Preserve the distinction between source consistency and requirement truth
    # in the exported artifact: the reference TC layout has no description cell.
    if "Test Evidence" in wb.sheetnames:
        del wb["Test Evidence"]
    evidence_ws = wb.create_sheet("Test Evidence")
    evidence_ws.append(["Function ID", "Function", "Sequence", "Observable", "Expected",
                        "Status", "Oracle", "Execution", "Source SHA256", "Source path", "Reason",
                        "Test Case ID", "Source hash scope", "Inputs JSON", "Basis", "Assumptions"])
    for cell in evidence_ws[1]:
        cell.font, cell.fill, cell.border = hdr_font, hdr_fill, thin
    evidence_ws.freeze_panes = "A2"
    # Count rows and address cells by (row, column): openpyxl ``ws.max_row`` and ``ws[row]`` (via ``max_column``) each
    # scan every cell, quadratic over this loop (KJPDS02_PV: 30+ minutes on this sheet alone).
    evidence_row = 1
    evidence_cols = evidence_ws.max_column
    for unit in units:
        for seq in all_sequences.get(unit["fid"], []):
            for var in dict.fromkeys([*(seq.get("expected") or {}), *(seq.get("expected_evidence") or {})]):
                value = (seq.get("expected") or {}).get(var, "")
                ev = (seq.get("expected_evidence") or {}).get(var) or {}
                evidence_ws.append([unit["fid"], unit.get("name", ""), seq.get("seq_num"), var,
                                    value, ev.get("status", "unrecorded"), ev.get("oracle_kind", "none"),
                                    ev.get("execution_status", "not_run"), ev.get("source_hash", ""),
                                    ev.get("source_path", ""), ev.get("reason", "provenance_missing"),
                                    rendered_tc_ids.get(unit["fid"], ""), ev.get("source_hash_scope", ""),
                                    json.dumps(seq.get("inputs") or {}, ensure_ascii=False, sort_keys=True),
                                    # (R2b) assigned vs unchanged_input, and what a derived value rests on
                                    ev.get("basis", ""), "; ".join(ev.get("assumptions") or ())])
                evidence_row += 1
                for cell in (evidence_ws.cell(evidence_row, c) for c in range(1, evidence_cols + 1)):
                    cell.font = data_font
                    # Treat all provenance strings as text, including paths/IDs
                    # beginning with spreadsheet formula characters.
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
    evidence_ws.auto_filter.ref = evidence_ws.dimensions
    for col in "ABCDEFGHIJKLMNOP":
        evidence_ws.column_dimensions[col].width = 24 if col not in "IJKP" else 48
    _write_mcdc_design_sheet(wb, units, all_sequences, rendered_tc_ids, thin, hdr_fill, hdr_font, data_font)
    # (R10) 소스 소견 — oracle 이 기대값을 내다가 증명한 미정의 동작(함수·종류별, 예시 벡터, 재현 여부 공시)
    # (R19) + 입력 목록 밖 읽기(함수가 초기값을 읽는데 시험 입력 목록에 없는 객체) — unit 마다 한 행
    from generators.source_findings import collect_findings, collect_input_gap_findings, write_source_findings_sheet
    write_source_findings_sheet(
        wb, collect_findings(units, all_sequences, rendered_tc_ids)
        + collect_input_gap_findings(units, _input_list_gaps(units, all_sequences), rendered_tc_ids),
        hdr_font, hdr_fill, thin)

    # --- Remove default sheet if we created new workbook ---
    if "Sheet" in wb.sheetnames and len(wb.sheetnames) > 1:
        del wb["Sheet"]

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))
    _logger.info("SUTS saved: %s", out)
    return str(out)


_MCDC_SHEET = "MCDC Design"
_MCDC_HEADERS = ["Test Case ID", "Function", "Decision ID", "Condition ID", "Pair ID", "Sequence A", "Sequence B",
                 "Inputs A JSON", "Inputs B JSON", "Truth A", "Truth B", "Decision A", "Decision B", "Retained",
                 "Decision Expression", "Decision Status", "Reason", "Source Kind", "Source SHA256",
                 "Search Complete", "Execution", "Reachability", "Evaluation", "Possible UB"]


def _write_mcdc_design_sheet(wb, units, all_sequences, rendered_tc_ids, border, hdr_fill, hdr_font, data_font):
    """MC/DC **설계** 근거 시트 — 결정별 독립 영향 쌍과, 쌍을 못 만든 결정의 사유(분모 유지).

    정본 시험 시트엔 이 정보를 담을 칸이 없다(열 구조 불변). 이 시트는 실행 커버리지가 아니다: `Execution` 은 늘
    `not_run`, `Reachability` 는 `unverified` 다. 내보내기(`tools/export_suts_vectorcast._attach_mcdc_design`)는 이 시트를
    입력 일치로만 재검증하고 커버리지로 승격하지 않는다.
    """
    from openpyxl.utils import get_column_letter

    if _MCDC_SHEET in wb.sheetnames:
        del wb[_MCDC_SHEET]
    ws = wb.create_sheet(_MCDC_SHEET)
    ws.append(_MCDC_HEADERS)
    for cell in ws[1]:
        cell.font, cell.fill, cell.border = hdr_font, hdr_fill, border
    ws.freeze_panes = "A2"


    for unit in units:
        report = unit.get("mcdc_design") or {}
        by_seq = {s.get("seq_num"): s for s in all_sequences.get(unit["fid"], [])}
        tc_id = rendered_tc_ids.get(unit["fid"], "")
        for decision in report.get("decisions") or []:
            common = [decision.get("expression", ""), decision.get("status", ""), decision.get("reason", ""),
                      decision.get("source_kind", ""), decision.get("source_hash", ""),
                      "yes" if decision.get("search_complete") else "no", "not_run", "unverified",
                      # (R2c) expression = 결정식만 평가 · source_path = 함수 실행 모델(지역변수·결정 전 갱신 포함)
                      decision.get("evaluation") or "expression"]
            pairs = decision.get("pairs") or []
            if not pairs:
                # 쌍 없는 결정도 한 행 — 빠지면 "MC/DC 설계 완료" 로 오독된다(분모에서 사라진다).
                ws.append([tc_id, unit.get("name", ""), decision.get("decision_id", ""), "", "", "", "", "", "", "",
                           "", "", "", "", *common, ""])
            for pair in pairs:
                retained = pair.get("retained_status", "")
                inputs = []
                for side in ("a", "b"):
                    seq = by_seq.get(pair.get(f"seq_{side}")) if retained == "retained" else None
                    inputs.append(json.dumps((seq or {}).get("inputs") if seq else pair.get(f"inputs_{side}") or {},
                                             ensure_ascii=False, sort_keys=True))
                # (R2c 리뷰 W7) 모델 실행이 결정 **이후** 가질 수 있는 UB — 쌍은 그 UB 가 없는 실행에서만 성립한다
                ub = sorted(set(pair.get("possible_ub_a") or []) | set(pair.get("possible_ub_b") or []))
                ws.append([tc_id, unit.get("name", ""), decision.get("decision_id", ""), pair.get("condition_id", ""),
                           pair.get("pair_id", ""),
                           pair.get("seq_a") if retained == "retained" else "",
                           pair.get("seq_b") if retained == "retained" else "",
                           inputs[0], inputs[1], _mcdc_truth_text(pair.get("truth_a"), pair.get("observed_a")),
                           _mcdc_truth_text(pair.get("truth_b"), pair.get("observed_b")),
                           "T" if pair.get("decision_a") else "F", "T" if pair.get("decision_b") else "F", retained,
                           *common, "+".join(ub)])
    # 한 번에 서식 — 결정마다 ``ws.max_row``(= 전 셀 ``max``)를 부르면 결정 수 × 셀 수로 커진다
    for row_cells in ws.iter_rows(min_row=2):
        for cell in row_cells:
            cell.font = data_font
            if isinstance(cell.value, str):
                cell.data_type = "s"   # 식·JSON 이 `=`·`-` 로 시작해도 수식으로 읽히지 않게
    ws.auto_filter.ref = ws.dimensions
    for idx, _ in enumerate(_MCDC_HEADERS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = 40 if idx in (8, 9, 15, 17, 19) else 16


def _write_suts_traceability_sheet(wb, units, border, hdr_fill, hdr_font, data_font):
    """Write traceability sheet mapping Components → Functions → SUTS TCs."""
    from openpyxl.styles import Alignment, PatternFill
    from openpyxl.utils import get_column_letter

    sheet_name = "3.Traceability"
    if sheet_name in wb.sheetnames:
        del wb[sheet_name]
    ws = wb.create_sheet(sheet_name)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    covered_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")

    ws.cell(row=1, column=1, value="Traceability Between [SUDS] and [SUTS]").font = hdr_font

    headers = ["#", "Component", "Function ID", "Function Name", "TC ID",
               "SRS Req ID", "Input Vars", "Output Vars", "Sequences", "Gen Method", "Status"]
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=3, column=ci, value=h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.border = border
        c.alignment = center

    widths = [5, 16, 16, 32, 22, 28, 10, 10, 10, 14, 10]
    for ci, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w

    row = 4
    for idx, u in enumerate(units, 1):
        tc_id = f"SwUTC_{u['fid']}"
        n_inp = len(u.get("input_vars", []))
        n_out = len(u.get("output_vars", []))
        has_io = n_inp > 0 or n_out > 0
        has_req = bool(u.get("srs_req_ids", ""))
        status = "Covered" if has_io else "No I/O"

        ws.cell(row=row, column=1, value=idx).font = data_font
        ws.cell(row=row, column=2, value=(u.get("component") or "").split("\n")[0]).font = data_font
        ws.cell(row=row, column=3, value=u["fid"]).font = data_font
        ws.cell(row=row, column=4, value=u["name"]).font = data_font
        ws.cell(row=row, column=5, value=tc_id).font = data_font
        ws.cell(row=row, column=6, value=u.get("srs_req_ids", "")).font = data_font
        ws.cell(row=row, column=7, value=n_inp).font = data_font
        ws.cell(row=row, column=8, value=n_out).font = data_font
        ws.cell(row=row, column=9, value=len(u.get("logic_flow", []))).font = data_font
        ws.cell(row=row, column=10, value=determine_gen_method(u)).font = data_font
        ws.cell(row=row, column=11, value=status).font = data_font

        for ci in range(1, 12):
            ws.cell(row=row, column=ci).border = border
            ws.cell(row=row, column=ci).alignment = wrap
            if has_io:
                ws.cell(row=row, column=ci).fill = covered_fill

        row += 1

    # Summary at bottom
    row += 1
    total = len(units)
    with_io = sum(1 for u in units if u.get("input_vars") or u.get("output_vars") or u.get("indirect_vars"))
    with_req = sum(1 for u in units if u.get("srs_req_ids"))
    ws.cell(row=row, column=1, value="Summary").font = hdr_font
    row += 1
    ws.cell(row=row, column=1, value="Total Functions").font = data_font
    ws.cell(row=row, column=2, value=total).font = data_font
    row += 1
    ws.cell(row=row, column=1, value="With I/O (Covered)").font = data_font
    ws.cell(row=row, column=2, value=with_io).font = data_font
    row += 1
    ws.cell(row=row, column=1, value="Coverage %").font = data_font
    ws.cell(row=row, column=2, value=f"{round(with_io / max(total, 1) * 100, 1)}%").font = data_font
    row += 1
    ws.cell(row=row, column=1, value="With SRS Req ID").font = data_font
    ws.cell(row=row, column=2, value=with_req).font = data_font
    row += 1
    ws.cell(row=row, column=1, value="SRS Traceability %").font = data_font
    ws.cell(row=row, column=2, value=f"{round(with_req / max(total, 1) * 100, 1)}%").font = data_font


def _create_suts_cover(wb, project_id, doc_id, version, asil_level):
    ws = wb.active
    ws.title = "Cover"
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    title_font = Font(name="맑은 고딕", size=24, bold=True)
    label_font = Font(name="맑은 고딕", size=9, bold=True)
    data_font = Font(name="맑은 고딕", size=9)
    thin = Border(left=Side(style="thin"), right=Side(style="thin"),
                  top=Side(style="thin"), bottom=Side(style="thin"))
    hdr_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # Column widths matching reference
    col_widths = {"A": 2.875, "B": 6.875, "C": 13.0, "D": 13.0, "E": 13.0,
                  "F": 13.0, "G": 13.0, "H": 4.625, "I": 6.875, "J": 13.0, "K": 10.625}
    for col, w in col_widths.items():
        ws.column_dimensions[col].width = w

    # B5:K5 merged — main title block (height=123 matching reference)
    ws.merge_cells("B5:K5")
    ws["B5"] = "Software Unit Test Specification\n(소프트웨어 단위테스트 명세서)"
    ws["B5"].font = title_font
    ws["B5"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[5].height = 123.0

    # I2 = "Doc. ID" label, J2:K2 merged = value
    ws["I2"] = "Doc. ID"
    ws["I2"].font = label_font
    ws["I2"].alignment = center
    ws.merge_cells("J2:K2")
    ws["J2"] = doc_id
    ws["J2"].font = data_font
    ws["J2"].alignment = center

    # I3 = "Version" label, J3:K3 merged = value
    ws["I3"] = "Version"
    ws["I3"].font = label_font
    ws["I3"].alignment = center
    ws.merge_cells("J3:K3")
    ws["J3"] = version
    ws["J3"].font = data_font
    ws["J3"].alignment = center

    info_rows = [
        ("Project", project_id),
        ("ASIL Level", asil_level),
        ("Status", "Draft"),
        ("Date", datetime.now().strftime("%Y-%m-%d")),
    ]
    for i, (label, value) in enumerate(info_rows):
        r = 21 + i
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
        ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=11)
        ws.cell(row=r, column=2, value=label).font = label_font
        ws.cell(row=r, column=2).fill = hdr_fill
        ws.cell(row=r, column=2).border = thin
        ws.cell(row=r, column=2).alignment = center
        ws.cell(row=r, column=6, value=value).font = data_font
        ws.cell(row=r, column=6).border = thin
        ws.cell(row=r, column=6).alignment = left


def _create_suts_history(wb, version):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    ws = wb.create_sheet("History")
    hdr_font = Font(name="맑은 고딕", size=10, bold=True)
    data_font = Font(name="맑은 고딕", size=9)
    thin = Border(left=Side(style="thin"), right=Side(style="thin"),
                  top=Side(style="thin"), bottom=Side(style="thin"))
    hdr_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    # Column widths matching reference: A:1.25, B:8.375, C:9.125, D:35.5, E:8.625, F:13.0, G:13.0, H:1.25
    ws.column_dimensions["A"].width = 1.25
    ws.column_dimensions["B"].width = 8.375
    ws.column_dimensions["C"].width = 9.125
    ws.column_dimensions["D"].width = 35.5
    ws.column_dimensions["E"].width = 8.625
    ws.column_dimensions["F"].width = 13.0
    ws.column_dimensions["G"].width = 13.0
    ws.column_dimensions["H"].width = 1.25
    ws.row_dimensions[2].height = 18.0
    ws.row_dimensions[3].height = 14.25

    ws.merge_cells("B2:G2")
    ws["B2"] = "▶ Revision History"
    ws["B2"].font = Font(name="맑은 고딕", size=12, bold=True)
    ws["B2"].alignment = Alignment(horizontal="left", vertical="center")

    headers = ["Version", "Date", "Description", "Author", "Reviewer", "Approver"]
    for i, h in enumerate(headers):
        c = ws.cell(row=4, column=2 + i, value=h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.border = thin
        c.alignment = center

    row_data = [
        (version, datetime.now().strftime("%Y.%m.%d"), "- Auto-generated", "Auto", "-", "-"),
    ]
    for ri, (ver, date, desc, author, reviewer, approver) in enumerate(row_data):
        r = 5 + ri
        for ci, val in enumerate([ver, date, desc, author, reviewer, approver]):
            cell = ws.cell(row=r, column=2 + ci, value=val)
            cell.font = data_font
            cell.border = thin


def _create_suts_intro(wb):
    ws = wb.create_sheet("1.Introduction")
    from openpyxl.styles import Font
    ws["A1"] = "Introduction"
    ws["A1"].font = Font(name="맑은 고딕", size=12, bold=True)
    ws["B3"] = "1.1 Purpose"
    ws["B3"].font = Font(name="맑은 고딕", size=10, bold=True)
    ws["B4"] = (
        "본 문서는 소프트웨어 유닛테스트 명세를 기술하는 문서이며, "
        "소프트웨어 유닛테스트 수행자에 의해서 작성된다."
    )
    ws["B6"] = (
        "유닛 소프트웨어 테스트의 근거가 되는 문서로서 정의며 "
        "유닛 소프트웨어 테스트 수행자에게 제공된다."
    )
    ws["B8"] = "1.2 Scope"
    ws["B8"].font = Font(name="맑은 고딕", size=10, bold=True)
    ws["B9"] = "본 문서는 유닛테스트 테스트 대상의 정의를 포함하며, 소프트웨어 단위 테스트의 사양을 정의하고 있다."


def _create_suts_test_env(wb):
    ws = wb.create_sheet("1.Test Environment")
    from openpyxl.styles import Font
    ws["A1"] = "Test Environments"
    ws["A1"].font = Font(name="맑은 고딕", size=12, bold=True)
    ws["B3"] = "STP의 SwUTE_01 과 테스트 환경으로 동일하다."
    ws["B6"] = "< End of Document >"


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

def generate_suts_quality_report(
    units: List[Dict[str, Any]],
    all_sequences: Dict[str, List[Dict[str, Any]]],
    total_source_functions: int = 0,
) -> Dict[str, Any]:
    total_tc = len(units)
    total_seq = sum(len(s) for s in all_sequences.values())
    total_inp = sum(len(u.get("input_vars", [])) for u in units)
    total_out = sum(len(u.get("output_vars", [])) for u in units)
    avg_seq = round(total_seq / max(total_tc, 1), 1)
    with_io = sum(
        1 for u in units
        if u.get("input_vars") or u.get("output_vars") or u.get("indirect_vars")
        or any(
            bool(s.get("inputs")) or bool(s.get("expected"))
            for s in all_sequences.get(u["fid"], [])
        )
    )
    with_logic = sum(1 for u in units if u.get("logic_flow"))

    gen_methods: Dict[str, int] = {}
    for u in units:
        gm = determine_gen_method(u)
        gen_methods[gm] = gen_methods.get(gm, 0) + 1

    components: Dict[str, int] = {}
    for u in units:
        comp = (u.get("component") or "Unknown").split("\n")[0]
        components[comp] = components.get(comp, 0) + 1

    # ⚠ 분모를 TC 수로 떨어뜨리지 않는다. 예전엔 `total_source_functions or total_tc`
    #   라, 소스 함수 수를 못 받으면 **자기 자신을 분모로** 써서 언제나 100.0% 가
    #   나왔다. 실측(KJPDS02_PV)에서는 함수 목록이 251개로 잘린 뒤 251/251 = 100% 로
    #   보고됐다 — 정본 1,014 함수 중 77.8% 를 버리고 "완전 커버" 라고 말한 것이다.
    #   재지 못했으면 **`None`**(미측정)이지 100% 가 아니다.
    src_total = int(total_source_functions or 0)
    func_coverage_pct: Optional[float] = (
        round(total_tc / src_total * 100, 1) if src_total > 0 else None
    )
    io_coverage_pct = round(with_io / max(total_tc, 1) * 100, 1)

    # (R70 N83) 안전 등급의 근거 분포(`collect_unit_functions` 의 `asil_evidence`)와 소스에 없는 override 전용 unit.
    #   `uds`/`uds+*` 는 SwUDS 표가 정한 것, `source` 는 소스 `@asil`, `override` 는 저장소 스냅샷(프로젝트 확인 없음),
    #   `sds-*` 는 SwDS 파티션 매칭, `none` 은 근거 없음(TBD). 예전엔 이 리포트가 등급의 근거를 하나도 싣지 않았다.
    asil_evidence: Dict[str, int] = {}
    for u in units:
        ev = str(u.get("asil_evidence") or "") or "none"
        asil_evidence[ev] = asil_evidence.get(ev, 0) + 1
    override_only = [str(u.get("name") or "") for u in units if u.get("override_only")]
    # (R71 N77) 변수 타입 해상 분포와, 선언은 있는데 모르는 타입이라 값을 비운 칸. 예전엔 그 칸이 전부 uint8 로
    #   지어낸 0/127/255 였다 — 이 수가 0 이 아니어야 정상이고, 그 칸의 값은 사람이 채운다.
    var_type_dist: Dict[str, int] = {}
    bounds_src_dist: Dict[str, int] = {}
    for u in units:
        for s in (u.get("bounds_source") or {}).values():
            bounds_src_dist[str(s)] = bounds_src_dist.get(str(s), 0) + 1
    # (R76 N97) 요구 ID 가 **무슨 근거로** 붙었나(`sds_partition` · `sts_mapping` · 둘 다 · `hsis`) — 예전엔 unit 에만 있었다.
    req_link_dist: Dict[str, int] = {}
    for u in units:
        if str(u.get("srs_req_ids") or "").strip():
            k = str(u.get("srs_req_link") or "") or "unrecorded"
            req_link_dist[k] = req_link_dist.get(k, 0) + 1
    # (R76 N95) 범위 밖 입력의 기대값을 **모른다**고 적은 칸(`[검증 필요] N`) — 마커는 정직하지만 몇 칸인지는 어디에도 없었다.
    verify_needed = sum(
        1 for u in units for q in all_sequences.get(u["fid"], [])
        for val in (q.get("expected") or {}).values() if str(val).startswith(_VERIFY_NEEDED_PREFIX))
    unknown_slots = 0
    units_with_unknown = 0
    for u in units:
        for t in (u.get("var_types") or {}).values():
            var_type_dist[str(t)] = var_type_dist.get(str(t), 0) + 1
        n_unknown = len(u.get("unknown_type_vars") or [])
        unknown_slots += n_unknown
        units_with_unknown += 1 if n_unknown else 0

    return {
        "asil_evidence_distribution": asil_evidence,
        "override_only_unit_count": len(override_only),
        "override_only_units": override_only[:20],
        "var_type_distribution": var_type_dist,
        # (R74) 경계값을 **무엇이** 정했나 — 설계서 범위 · enum 값 집합 · HSIS 값 범위 · 타입 전폭 · 모름.
        "bounds_source_distribution": bounds_src_dist,
        # 문서의 범위가 선언 타입을 넘어 쓰지 않은 것(문서 오류 후보) — 중복 제거한 이름 목록 앞 20개와 수.
        "range_conflicts": sorted({c for u in units for c in (u.get("range_conflicts") or [])})[:20],
        "range_conflict_count": len({c for u in units for c in (u.get("range_conflicts") or [])}),
        # (R76 N98) 포인터 선언에 적힌 주소 범위 — 문서 오류가 아니라 **다른 축**이라 위 수에서 뺐다(값 처리는 같다: 타입 전폭).
        "pointer_address_range_count": len({c for u in units for c in (u.get("pointer_address_ranges") or [])}),
        "pointer_address_ranges": sorted({c for u in units for c in (u.get("pointer_address_ranges") or [])})[:20],
        "srs_req_link_distribution": req_link_dist,
        "verify_needed_expected_slots": verify_needed,
        "mcdc_design_summary": summarize_mcdc_design(units),
        # (R10) 소스 소견 — 기대값 도출 중 증명된 미정의 동작(함수·종류별). 재현은 별도 스크립트(not_run).
        "source_findings": _summarize_source_findings(units, all_sequences),
        "expected_evidence_summary": summarize_expected_evidence([
            seq for seqs in all_sequences.values() for seq in seqs]),
        "units_with_srs_req_ids": sum(1 for u in units if str(u.get("srs_req_ids") or "").strip()),
        "unknown_type_var_slots": unknown_slots,
        "units_with_unknown_type_vars": units_with_unknown,
        "total_test_cases": total_tc,
        "total_sequences": total_seq,
        "avg_sequences_per_tc": avg_seq,
        "total_input_vars": total_inp,
        "total_output_vars": total_out,
        "with_io_count": with_io,
        "with_logic_count": with_logic,
        "function_coverage_pct": func_coverage_pct,
        "io_coverage_pct": io_coverage_pct,
        "total_source_functions": src_total,
        "gen_method_distribution": gen_methods,
        "component_distribution": components,
    }


# ---------------------------------------------------------------------------
# Document validation
# ---------------------------------------------------------------------------

_SUTS_SPEC_SHEET = "2.SW Unit Test Spec"


def _find_spec_sheet(sheetnames: Any) -> Optional[str]:
    """명세 시트의 **실제 이름** — 글자 그대로 있으면 그것, 없으면 번호 접두만 다른 시트. 없으면 None."""
    names = list(sheetnames or [])
    if _SUTS_SPEC_SHEET in names:
        return _SUTS_SPEC_SHEET
    want = _sheet_base_name(_SUTS_SPEC_SHEET)
    return next((n for n in names if _sheet_base_name(n) == want), None)


def validate_suts_xlsm(
    xlsm_path: str,
    expected_tc_range: Optional[tuple] = None,
    expected_seq_range: Optional[tuple] = None,
) -> Dict[str, Any]:
    """Validate generated SUTS XLSM for structural and data quality.

    Returns dict with 'valid' bool, 'issues' list, 'warnings' list, and 'stats' dict.

    ⚠ 이 문장은 오랫동안 **거짓이었다**: `warnings` 는 선언만 돼 있고 한 번도 채워지지
      않았으며, 4개 반환 경로 중 2곳엔 키 자체가 없었다. 그런데 API 는 세 문서 종류
      모두에 `warnings` 를 실어 내보내(`backend/helpers/common.py::
      _build_excel_artifact_payload` 가 `validation` 을 본문째 전달)
      **항상 "경고 없음"** 으로 읽혔다 — 점검이 하나도 없다는 사실이 빈 배열에 숨었다.
      `issues` 는 `valid` 를 뒤집지만 `warnings` 는 안 뒤집는다. 그래서 경고는
      리포트에 자리가 있어야만 사람 눈에 닿는다.
    """
    issues: List[str] = []
    warnings: List[str] = []
    stats: Dict[str, Any] = {}

    try:
        from openpyxl import load_workbook
    except ImportError:
        return {"valid": False, "issues": ["openpyxl not installed"], "warnings": [], "stats": {}}

    p = Path(xlsm_path)
    if not p.exists():
        return {"valid": False, "issues": [f"File not found: {xlsm_path}"], "warnings": [], "stats": {}}

    try:
        wb = load_workbook(str(p), read_only=True, data_only=True)
    except Exception as e:
        return {"valid": False, "issues": [f"Cannot open: {e}"],
                "warnings": warnings, "stats": {}}

    # (R77 리뷰 I4) 명세 시트도 **번호 접두를 떼고** 찾는다 — 글자 그대로만 찾으면 이름이 `SW Unit Test Spec` 인 양식에서
    #   "필수 시트 없음" 한 줄만 남고 아래 TC·시퀀스 검사가 통째로 건너뛰어진다(0 을 세고 조용해지는 fail-open).
    _spec_sheet = _find_spec_sheet(wb.sheetnames)
    if _spec_sheet is None:
        issues.append(f"Missing required sheet: {_SUTS_SPEC_SHEET}")

    expected_sheets = ["Cover", "History", "1.Introduction", "1.Test Environment", "3.Traceability"]
    stats["sheets"] = wb.sheetnames
    stats["sheet_count"] = len(wb.sheetnames)
    # (R77 N114) ① 시트는 **번호 접두를 떼고** 찾는다 — 정본(KJPDS02 SwUTS)의 시트 이름은 `Introduction` 인데 여기는
    #   `1.Introduction` 만 찾아, 시트가 **있는데도** 라이브 SUTS 가 매번 `valid: False` 였다(R75·R76 실측, 사유 이 한 줄).
    #   ② "선택" 시트의 부재는 판정을 뒤집지 않는다 — 형제 검증기(`validate_sts_xlsm`)는 처음부터 경고였다. 필수 시트는 위에서 본다.
    _present = {_sheet_base_name(n) for n in wb.sheetnames}
    for s in expected_sheets:
        if _sheet_base_name(s) not in _present:
            warnings.append(f"Optional sheet missing: {s}")

    if _spec_sheet is not None:
        ws = wb[_spec_sheet]
        # ⚠ 레이아웃을 **하드코딩하지 않는다**. 예전엔 `min_row=7`·`max_col=149`·
        #   `row[12]`(옛 Seq.No)·`row[13:62]`(옛 Input) 가 박혀 있었다. 정본 레이아웃
        #   으로 바꾸자 검증기가 시퀀스 7,267건을 **1,576건으로** 셌다(-5,691).
        #   파일은 멀쩡한데 검증기만 틀려서 정상 산출물을 결함으로 신고했다.
        #   상수에서 파생하면 레이아웃이 또 바뀌어도 같이 따라간다.
        max_col = min(int(ws.max_column or _RELATED_COL), _RELATED_COL)
        stats["max_col"] = max_col

        tc_count = 0
        seq_count = 0
        empty_io_tcs = 0
        last_row = _HEADER_ROW
        for row_idx, row in enumerate(
            ws.iter_rows(min_row=_DATA_START_ROW, max_col=max_col, values_only=True),
            start=_DATA_START_ROW,
        ):
            last_row = row_idx
            tc_id = row[_COL_TC_ID - 1] if len(row) >= _COL_TC_ID else None
            if tc_id and str(tc_id).startswith("SwUTC"):
                tc_count += 1
                has_input = any(
                    v not in (None, "")
                    for v in row[_INPUT_COL_START - 1:min(_INPUT_COL_END, len(row))]
                )
                has_output = any(
                    v not in (None, "")
                    for v in row[_OUTPUT_COL_START - 1:min(_OUTPUT_COL_END, len(row))]
                )
                if not has_input and not has_output:
                    empty_io_tcs += 1
            seq_val = row[_SEQ_COL - 1] if len(row) >= _SEQ_COL else None
            if seq_val is not None and str(seq_val).strip():
                seq_count += 1

        stats["max_row"] = last_row

        stats["tc_count"] = tc_count
        stats["seq_count"] = seq_count
        stats["empty_io_tc_count"] = empty_io_tcs
        stats["avg_seq_per_tc"] = round(seq_count / max(tc_count, 1), 1)

        if tc_count == 0:
            issues.append("No test cases (SwUTC_*) found")
        if seq_count == 0:
            issues.append("No test sequences found")
        if empty_io_tcs > tc_count * 0.5:
            issues.append(f"Over 50% TCs lack I/O variables ({empty_io_tcs}/{tc_count})")
        elif empty_io_tcs:
            # ⚠ 50% **이하**는 예전에 통째로 침묵했다 — TC 절반이 I/O 없이 나가도
            #   `issues` 가 비어 `valid=True` 이고 리포트는 아무 말도 안 했다.
            #   임계를 새로 발명하지 않는다: "0 보다 크다" 는 산술적 사실만 적는다.
            warnings.append(f"{empty_io_tcs}/{tc_count} TCs lack I/O variables")
        if tc_count and seq_count < tc_count:
            # 시퀀스가 TC 수보다 적다 = 일부 TC 에 시험 절차가 없다. 역시 사실 그대로.
            warnings.append(f"{tc_count - seq_count} TCs have no test sequence "
                            f"(seq {seq_count} < tc {tc_count})")

        if expected_tc_range:
            lo, hi = expected_tc_range
            if tc_count < lo or tc_count > hi:
                issues.append(f"TC count {tc_count} outside expected range [{lo}, {hi}]")

        if expected_seq_range:
            lo, hi = expected_seq_range
            if seq_count < lo or seq_count > hi:
                issues.append(f"Sequence count {seq_count} outside expected range [{lo}, {hi}]")

    wb.close()
    # ⚠ `warnings` 는 **모든** 반환 경로에 있어야 한다. 예전엔 4경로 중 2곳에만
    #   있었고 docstring 은 항상 준다고 적혀 있었다 — 소비처가 `result["warnings"]`
    #   로 읽으면 경로에 따라 KeyError 였다.
    return {"valid": len(issues) == 0, "issues": issues,
            "warnings": warnings, "stats": stats}


@contextmanager
def _resolved_doc_input(path: Optional[str], label: str):
    """문서 입력(SRS/UDS/HSIS)을 **로컬에서 열 수 있는 경로**로 확보한다.

    과거엔 `Path(p).is_file()`만 봤다. cloudium 모드에서 U:\\ 같은 경로는 backend 프로세스에
    권한이 없어(worker exe만 접근 가능) 항상 False가 되고, 보강 블록이 **경고 한 줄 없이**
    통째로 skip됐다 — 산출물엔 "요구 ID 없음"으로만 남아 원인을 알 수 없었다.

    로컬에 있으면 원래 경로를 그대로 돌려주고(추가 I/O 0), worker에만 있으면 resolver로
    bytes를 읽어 임시 파일로 materialize한 뒤 종료 시 지운다. 어느 쪽도 아니면 None을
    yield하되 **사유를 warning으로 남긴다**.

    Yields: 열 수 있는 로컬 경로(str) 또는 None.
    """
    raw = str(path or "").strip()
    if not raw:
        yield None
        return
    try:
        if Path(raw).is_file():
            yield raw
            return
    except OSError as exc:      # 권한 거부(U:\ 등) — 로컬 판정 불가일 뿐 부재는 아니다
        _logger.debug("%s: 로컬 stat 실패(%s) — resolver로 재시도", label, exc)

    resolver = None
    try:
        from backend.services.file_resolver import get_resolver
        resolver = get_resolver()
    except Exception as exc:    # standalone 실행 등 backend 미가용
        _logger.warning("%s 입력을 건너뜀 — 로컬에 없고 resolver도 불가: %s (%s)", label, raw, exc)
        yield None
        return

    try:
        if not resolver.is_file(raw):
            _logger.warning("%s 입력을 건너뜀 — resolver(mode=%s)에도 없음: %s",
                            label, getattr(resolver, "mode", "?"), raw)
            yield None
            return
        data = resolver.read_bytes(raw)
    except Exception as exc:
        _logger.warning("%s 입력 읽기 실패 — 보강 생략: %s (%s)", label, raw, exc)
        yield None
        return

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=Path(raw).suffix or ".bin", prefix=f"{label}_", delete=False,
        ) as fh:
            fh.write(data)
            tmp_path = fh.name
        _logger.info("%s: worker 경로를 임시 파일로 materialize (%d bytes)", label, len(data))
        yield tmp_path
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                _logger.debug("%s: 임시 파일 정리 실패 %s", label, tmp_path)


def validate_sts_xlsm(xlsm_path: str) -> Dict[str, Any]:
    """STS 검증 — 구현은 generators.sts로 이관됐다(하위호환 re-export).

    이 함수가 여기 있던 동안 SUTS 레이아웃 상수(5/6/4열)로 STS를 읽어 Action·Expected가
    비어도 통과시켰다. 열 스키마는 산출물을 쓰는 모듈이 소유해야 한다 — generators.sts의
    `_STS_SCHEMA`가 writer·validator 공통 출처다. 기존 import 경로는 그대로 둔다.
    """
    from generators.sts import validate_sts_xlsm as _impl
    return _impl(xlsm_path)


# ---------------------------------------------------------------------------
# Top-level pipeline
# ---------------------------------------------------------------------------

def _override_only_entry(name: str, ovr_info: Dict[str, Any], fid: str) -> Dict[str, Any]:
    """override 스냅샷(`docs/uds_function_swcom_override.json`)에만 있고 소스에 없는 함수의 자리표시 엔트리.

    (R70 N83) 이 엔트리의 근거는 저장소 스냅샷뿐이다 — 소스도 주석도 없다. 값을 준 단계가 라벨을 단다(R68 규약):
    값이 있으면 `override`, 없으면 TBD 에 `default`. 예전엔 라벨을 아예 안 적어 `collect_unit_functions` 의 근거
    표지가 이 값을 소스 `@asil` 로 읽었다. `override_only` 는 하류가 "소스에 없는 unit" 을 세어 보고하는 표지다
    (prototype 은 자리표시 — 실 시그니처가 아니다). 본체 인라인이면 전체 생성 없이는 검증할 수 없어 뽑아 둔다.
    """
    from report_gen.provenance import unrecorded_source

    o_asil = str(ovr_info.get("asil") or "").strip()
    o_rel = str(ovr_info.get("related") or "").strip()
    sc = int(ovr_info.get("swcom") or 0)
    return {
        "id": fid,
        "name": name,
        "prototype": f"void {name}(void)",
        "description": "",
        # 하류 소비자 없음 — 소스 단계 엔트리와 같은 키 집합을 갖게 하는 규약 일관성 목적(리뷰 I6).
        "description_source": unrecorded_source(""),
        "asil": o_asil or "TBD",
        "asil_source": "override" if o_asil else unrecorded_source("TBD"),
        "related": o_rel or "TBD",
        "related_source": "override" if o_rel else unrecorded_source("TBD"),
        "inputs": [],
        "outputs": [],
        "logic_flow": [],
        "calls_list": [],
        "file": "",
        "module_name": f"SwCom_{sc:02d}",
        "override_only": True,
    }


_OVERRIDE_JSON_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "docs" / "uds_function_swcom_override.json",
    Path(__file__).resolve().parent / "docs" / "uds_function_swcom_override.json",
)


def supplement_override_only(function_details: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """override 스냅샷에만 있고 소스에 없는 함수를 자리표시 엔트리로 **보충**한다(필터 아님). 제자리 변경.

    반환: `{"found": 목록 파일 유무, "list_size", "source": 보충 전 함수 수, "in_list": 목록 일치 수, "added": 보충 수,
    "added_names": [...]}`.

    (R70 리뷰 W1) 생성기(`generate_suts`)와 준비 게이트 측정(`docgen_test_materials.measure`)이 **같은 함수**를 불러야
    게이트가 산출물과 같은 unit 목록을 잰다 — 이 블록이 `generate_suts` 안에 인라인이던 동안 측정 경로는 보충을 안 타서
    스냅샷 전용 unit 이 게이트에선 구조적으로 0 이었다. 실패(파일 손상 등)는 예외로 올린다 — 호출부가 사유를 남긴다.
    """
    stats: Dict[str, Any] = {"found": False, "list_size": 0, "source": len(function_details),
                             "in_list": 0, "added": 0, "added_names": []}
    import json as _json

    for ovr_path in _OVERRIDE_JSON_CANDIDATES:
        if not ovr_path.exists():
            continue
        ovr_data = _json.loads(ovr_path.read_text(encoding="utf-8"))
        stats["found"] = True
        stats["list_size"] = len(ovr_data)
        if not ovr_data:
            break
        names = set(ovr_data.keys())
        names_lower = {n.lower() for n in names}
        # ⚠ 여기서 걸러내지 않는다(호출부 주석 참조). 목록 밖 함수도 그대로 둔다.
        stats["in_list"] = sum(
            1 for info in function_details.values()
            if isinstance(info, dict) and (
                str(info.get("name") or "") in names or str(info.get("name") or "").lower() in names_lower)
        )
        existing = {str(info.get("name") or "").lower() for info in function_details.values() if isinstance(info, dict)}
        added = 0
        # (R70 N89) 자리표시 id 는 **비어 있는** 번호여야 한다. 예전 식 `SwUFn_{swcom}{99-n}` 은 함수가 99개 이상인
        #   모듈(KJPDS02 SwCom_13 126개 · SwCom_35)의 실 함수 id 와 겹쳐 그 함수를 **덮어썼다** — 라이브 5개
        #   (`s_Ap_PreviousCtrl_ResetFlags` 등)가 SUTS 에서 조용히 사라졌다(1,146+27 이 1,168 이던 이유).
        next_slot: Dict[int, int] = {}
        for ovr_name, ovr_info in ovr_data.items():
            if ovr_name.lower() in existing:
                continue
            info = ovr_info if isinstance(ovr_info, dict) else {}
            sc = int(info.get("swcom") or 0)
            slot = next_slot.get(sc, 99)
            fid = f"SwUFn_{sc:02d}{slot:02d}"
            while fid in function_details and slot > 0:
                slot -= 1
                fid = f"SwUFn_{sc:02d}{slot:02d}"
            if fid in function_details:
                # 두 자리 번호가 다 찼다 — 본 생성기의 3자리 규약과 같은 꼴로 비켜 선다.
                fid = f"SwUFn_{sc:02d}{900 + added:03d}"
            next_slot[sc] = slot - 1
            function_details[fid] = _override_only_entry(ovr_name, info, fid)
            added += 1
            stats["added_names"].append(ovr_name)
        stats["added"] = added
        break
    return stats


def _link_units_to_requirements(units: List[Dict[str, Any]], fid_to_reqs: Dict[str, List[str]]) -> int:
    """STS 요구→함수 매핑을 뒤집은 `fid → [요구 ID]` 로 unit 의 `srs_req_ids` 를 채운다. 반환은 매핑이 닿은 unit 수.

    (R74 N90 · 리뷰 W2) 수집 단계(SwDS 파티션 직조회)가 이미 적은 ID 와 **합친다** — 건너뛰면 그 unit 만 옛 경로의 부분
    집합으로 남는다. 전량을 적고(앞 4개 절단 없음) 어느 근거인지는 `srs_req_link`(`sds_partition`·`sts_mapping`·둘 다)가 말한다.
    """
    linked = 0
    for unit in units:
        prev = [x.strip() for x in str(unit.get("srs_req_ids") or "").split(",") if x.strip()]
        mapped = list(dict.fromkeys(fid_to_reqs.get(str(unit.get("fid") or "")) or []))
        ids = list(dict.fromkeys(prev + mapped))
        if not ids:
            continue
        unit["srs_req_ids"] = ", ".join(ids)
        unit["srs_req_link"] = "+".join(
            name for name, on in (("sds_partition", bool(prev)), ("sts_mapping", bool(mapped))) if on)
        linked += 1 if mapped else 0
    return linked


def _note_unknown_type_slots(validation: Dict[str, Any], quality: Dict[str, Any]) -> None:
    """(R71 N77 · 리뷰 W5) 검증기의 "I/O 변수 없는 TC" 는 시트만 보므로 **일부러 비운 칸**(타입 미상)과 재료를 잃은 칸을
    같은 숫자로 센다. 비운 칸의 수를 경고 옆에 같이 적어 두 0 을 갈라 읽게 한다(0 이면 적지 않는다)."""
    unk = int((quality or {}).get("unknown_type_var_slots") or 0)
    if unk:
        validation.setdefault("warnings", []).append(
            f"타입 미상으로 값을 비운 입력/기대 칸 {unk}개({(quality or {}).get('units_with_unknown_type_vars', 0)} unit) — "
            "구조체·enum·void*·모르는 typedef 는 경계값을 지어내지 않는다. 사람이 채우거나 typedef 를 등록할 것")


def _source_function_count(function_details: Dict[str, Dict[str, Any]]) -> int:
    """품질 리포트의 함수 커버리지 **분모** — 소스에서 찾은 함수 수. (R70 N83) 스냅샷 전용 자리표시 엔트리는 소스 함수가
    아니므로 빼야 한다: 넣으면 KJPDS02 에서 928/1,168 = 79.5%(게이트 80 미달)가 되는데 소스 함수 기준으론 928/1,141 = 81.3% 다."""
    return sum(1 for i in function_details.values() if isinstance(i, dict) and not i.get("override_only"))


def generate_suts(
    source_root: str,
    output_path: str,
    template_path: Optional[str] = None,
    project_config: Optional[Dict[str, Any]] = None,
    ai_config: Optional[Dict[str, Any]] = None,
    max_sequences: int = _DEFAULT_SEQ_COUNT,
    on_progress: Optional[Any] = None,
    srs_docx_path: Optional[str] = None,
    sds_docx_path: Optional[str] = None,
    uds_path: Optional[str] = None,
    hsis_path: Optional[str] = None,
    target_function_names: Optional[List[str]] = None,
    scope: str = "suds",
    tc_profile: str = "",
) -> Dict[str, Any]:
    """Top-level SUTS generation pipeline.

    Args (추가):
        tc_profile: `""`/`"reference"`(기본) = 정본 규모. `"extended"` = 시퀀스 상한 없이 + 확장 전략
            (`generate_sequences(extended=True)`). 단일 정의는 `generators/tc_profile.py`.
        scope: `"suds"`(기본) = SwUDS 설계 ID 가 있는 함수만 — **정본과 같은 범위**.
            `"source"` = 소스에서 찾은 함수 전부. SwUDS 문서가 없으면 `"suds"` 여도
            좁히지 않고 그 사실을 보고한다.

    Args:
        source_root: Root directory of C source code
        output_path: Path for output XLSM file
        template_path: Optional SUTS template XLSM
        project_config: Optional config dict
        ai_config: Optional AI config dict for Gemini enhancement
        max_sequences: Maximum sequences per TC
        on_progress: Optional callback(pct: int, message: str) for progress updates
        srs_docx_path: Optional path to SRS DOCX for requirement ID enrichment
        sds_docx_path: Optional path to SDS DOCX for ASIL/design context
        uds_path: Optional path to UDS DOCX/XLSM for function descriptions

    Returns:
        Dict with keys: output_path, quality_report, test_case_count, etc.
    """
    def _progress(pct: int, msg: str):
        _logger.info("[%d%%] %s", pct, msg)
        if on_progress:
            try:
                on_progress(pct, msg)
            except Exception:
                pass

    _logger.info("=== SUTS Generation Start ===")
    t0 = time.time()
    target_name_set = {
        str(name or "").strip().lower()
        for name in (target_function_names or [])
        if str(name or "").strip()
    }

    _progress(5, "소스 코드 파싱 시작")
    globals_info_map: Dict[str, Dict[str, str]] = {}
    try:
        try:
            from backend.helpers import _get_source_sections_cached

            report_data = _get_source_sections_cached(source_root)
        except Exception:
            from report_generator import generate_uds_source_sections

            report_data = generate_uds_source_sections(source_root)
        function_details = report_data.get("function_details", {})
        globals_info_map = report_data.get("globals_info_map", {}) or {}
        if not function_details:
            raise ValueError("generate_uds_source_sections returned no function_details")
    except Exception as e:
        _logger.warning("Full UDS source parse failed, trying lightweight: %s", e)
        function_details = _lightweight_parse(source_root)

    if target_name_set:
        function_details = {
            fid: info
            for fid, info in function_details.items()
            if isinstance(info, dict) and str(info.get("name") or "").strip().lower() in target_name_set
        }

    _progress(25, f"소스 파싱 완료 - {len(function_details)}개 함수 발견")

    # 함수 단위 override 맵 — **보강·보충 전용**. 필터로 쓰지 않는다.
    #
    # ⚠ 예전엔 이 목록에 **없는 함수를 전부 버렸다**("레퍼런스에 있는 함수만 포함").
    #   그 결과가 실측으로 드러났다(2026-08-11, KJPDS02_PV):
    #     · 소스 파싱 900~1,153 함수 → override 251개로 잘림 → TC 251개
    #     · 정본 SwUTS 는 1,014 함수. 그중 **782개(77.8%)가 목록에 없어 침묵 탈락**
    #     · override 251개 중 정본에 실재하는 건 223개뿐 — 28개는 없는 함수다
    #   이 파일은 **저장소**(`docs/`)에 있어 프로젝트가 바뀌어도 같은 251개로 자른다.
    #   과거 어느 스냅샷의 목록이 지금 프로젝트의 시험 범위를 정하고 있었다.
    #
    #   게다가 커버리지 분모가 **필터 후 값**이라 언제나 251/251 = "함수 커버리지
    #   100.0%" 로 보고됐다 — 77.8% 를 버리고 100% 라고 말하는 fail-open 이다.
    #
    #   그래서 필터를 걷어내고 **탈락 대신 보충만** 한다(목록에 있는데 소스에 없는
    #   함수는 종전대로 빈 엔트리로 추가한다 — 그건 정보를 더하지 빼지 않는다).
    #   (R70) 보충 자체는 `supplement_override_only` — 준비 게이트 측정도 같은 함수를 부른다(리뷰 W1).
    try:
        _ovr = supplement_override_only(function_details)
        if _ovr["found"] and _ovr["list_size"]:
            # 침묵 금지 — 목록과 소스가 얼마나 어긋나는지 그대로 보고한다.
            _progress(
                28,
                f"override 보강: 소스 {_ovr['source']}개 중 목록 일치 {_ovr['in_list']}개 "
                f"(+{_ovr['added']} 보충 → {len(function_details)}개). 필터 아님",
            )
            _logger.info(
                "uds override: source=%d in_list=%d added=%d total=%d (목록 %d개 — 필터로 쓰지 않는다)",
                _ovr["source"], _ovr["in_list"], _ovr["added"], len(function_details), _ovr["list_size"],
            )
    except Exception as _ovr_exc:  # noqa: BLE001 — 보충 실패가 생성을 막으면 안 되지만 조용해서도 안 된다(리뷰 W3)
        _logger.warning("override 보강 실패 — 건너뜀(산출물은 소스 함수만): %s: %s", type(_ovr_exc).__name__, _ovr_exc)

    if sds_docx_path:
        _progress(29, "SDS 설계 컨텍스트 로드 중")
    _sds_map = _resolve_sds_map(sds_docx_path)

    _progress(30, "유닛 함수 수집 중")
    # ── SwUDS 입출력 표 — 시험 변수 이름의 **정본 출처** ──────────────────────
    # ⚠ 여기서 읽는다. 아래 UDS 보강 블록(설명·설계 ID)은 `collect_unit_functions`
    #   **뒤**라 늦다 — 이름 대체는 배열 원소 확장보다 앞서야 하고, 확장은 collect
    #   안에서 일어난다. 문서를 두 번 materialize 하는 비용(cloudium 경유)은 감수한다.
    _uds_io: Optional[Dict[str, Any]] = None
    with _resolved_doc_input(uds_path, "UDS(입출력)") as _uds_io_local:
        if _uds_io_local:
            try:
                from generators.uds_unit_io import load_uds_unit_io
                _uds_io = load_uds_unit_io(_uds_io_local)
            except Exception as _e:  # noqa: BLE001 — 실패하면 소스 파싱으로 간다
                _logger.warning("SwUDS 입출력 읽기 실패 — 소스 파싱 이름을 쓴다: %s", _e)
    units = collect_unit_functions(function_details, globals_info_map, sds_map=_sds_map,
                                   uds_io_map=_uds_io,
                                   struct_members=report_data.get("struct_member_arrays") or {})
    attach_unit_sources(units, report_data.get("source_files"), report_data.get("project_context"))

    if not units:
        _logger.warning("No unit functions found!")
        return {
            "output_path": "",
            "quality_report": {},
            "test_case_count": 0,
            "elapsed_seconds": round(time.time() - t0, 1),
            "error": "No functions found in source code",
        }

    _progress(35, f"{len(units)}개 유닛 함수 수집 완료")

    # ── SRS requirement ID enrichment ────────────────────────────────────
    # 입력 경로는 resolver 경유로 확보한다(worker-only 입력의 침묵 skip 차단 —
    # _resolved_doc_input 주석 참조). 아래 UDS/HSIS 블록도 같은 규약.
    #
    # (R74 N90) 예전엔 요구 본문에서 `…_init|_main|_get…` 꼴 함수 이름을 **정규식으로 찾았다** — KJPDS02 SwRS 68 요구에서
    #   후보 0건, 요구 ID 가 붙은 unit 0/933(라이브 로그 "0 units have req IDs now"). 요구는 함수 이름을 적지 않는다.
    #   STS 가 쓰는 요구→함수 매핑(`map_requirements_to_functions`: 주석 Related · SwDS 파티션 · SwUDS 설계-ID 브리지)을
    #   그대로 뒤집어 쓴다 — 같은 실측에서 896/933 unit 에 닿는다. 두 문서가 **같은 매핑**을 봐야 추적성이 맞는다.
    # (R76 N101) 보강 블록은 실패해도 생성을 막지 않는다(넓은 except) — 그래서 실패가 **로그에만** 남았고, 산출물은
    #   "요구 ID 없음"·"설명 없음" 으로만 보였다. 어느 단계가 왜 죽었는지 품질 리포트와 검증 경고에 싣는다.
    _enrich_errors: List[Dict[str, str]] = []

    def _enrich_failed(stage: str, exc: BaseException) -> None:
        _enrich_errors.append({"stage": stage, "error": f"{type(exc).__name__}: {exc}"[:300]})

    with _resolved_doc_input(srs_docx_path, "SRS") as _srs_local:
        if _srs_local:
            _progress(36, "SRS 요구사항 ID 보강 중")
            try:
                from generators.sts import load_uds_design_ids as _sts_design_ids
                from generators.sts import map_requirements_to_functions, parse_srs_docx_tables
                srs_reqs = parse_srs_docx_tables(_srs_local)
                if srs_reqs:
                    _design_ids: Dict[str, Any] = {}
                    with _resolved_doc_input(uds_path, "UDS(설계 ID 브리지)") as _uds_bridge:
                        if _uds_bridge:
                            _design_ids = _sts_design_ids(_uds_bridge) or {}
                    # ⚠ `sds_map=None` 은 저장소 `docs/` 글롭(프로젝트 무관)이다 — 없으면 빈 맵을 명시한다.
                    _req_to_fids = map_requirements_to_functions(
                        srs_reqs, function_details, sds_map=_sds_map or {}, uds_design_ids=_design_ids or None)
                    _fid_to_reqs: Dict[str, List[str]] = {}
                    for _rid, _fids in _req_to_fids.items():
                        for _f in _fids:
                            _fid_to_reqs.setdefault(_f, []).append(_rid)
                    _linked = _link_units_to_requirements(units, _fid_to_reqs)
                    _logger.info(
                        "SRS enrichment: %d reqs parsed, %d/%d units linked via the STS mapping "
                        "(설계 ID 브리지 %s) — 요구 ID 보유 unit %d",
                        len(srs_reqs), _linked, len(units), "on" if _design_ids else "off",
                        sum(1 for u in units if u.get("srs_req_ids")))
            except Exception as _e:  # noqa: BLE001 — 보강 실패가 생성을 막지 않는다. 대신 공시한다
                _logger.warning("SRS enrichment skipped: %s", _e)
                _enrich_failed("srs_req_ids", _e)

    # ── UDS function description enrichment ──────────────────────────────
    with _resolved_doc_input(uds_path, "UDS") as _uds_local:
        if _uds_local:
            _progress(37, "UDS 함수 설명 보강 중")
            try:
                from generators.sts import _load_uds_descriptions
                uds_descs = _load_uds_descriptions(_uds_local)
                if uds_descs:
                    enriched_count = 0
                    for unit in units:
                        fn_lower = unit["name"].lower()
                        uds_desc = uds_descs.get(fn_lower)
                        if uds_desc and len(uds_desc) > len(unit.get("description") or ""):
                            unit["description"] = uds_desc
                            enriched_count += 1
                    _logger.info("UDS descriptions enriched for %d units", enriched_count)
            except Exception as _e:  # noqa: BLE001
                _logger.warning("UDS description enrichment skipped: %s", _e)
                _enrich_failed("uds_description", _e)

            # ── 설계 ID(SwUFn_xxxx) — SUDS 칸과 TC_ID 의 근거 ──────────────
            # 정본 실측: `TC_ID = "SwUTC_" + SUDS` 가 1,013/1,014 에서 성립한다.
            # ⚠ 못 찾으면 **비운다**. 예전엔 소스 파싱 순번(`SwUFn_{n:04d}`)을 넣어
            #   모양만 맞고 다른 설계 요소를 가리켰다(정본과 교집합 178/251).
            try:
                from generators.uds_design_ids import load_uds_design_ids, resolve_design_id
                _design = load_uds_design_ids(_uds_local)
                if _design.get("by_name"):
                    _hit = 0
                    for unit in units:
                        did = resolve_design_id(_design, unit.get("name"))
                        if did:
                            unit["suds_id"] = did
                            _hit += 1
                    _logger.info(
                        "UDS design IDs: %d/%d units matched (문서 %d ids · 동명이인 %d 제외)",
                        _hit, len(units), len(_design["by_name"]), len(_design.get("ambiguous") or []),
                    )
            except Exception as _e:  # noqa: BLE001
                _logger.warning("UDS design-id enrichment skipped: %s", _e)
                _enrich_failed("uds_design_ids", _e)

    # ── 시험 범위 — 기본은 **SwUDS 기반**(정본과 같은 범위) ────────────────────
    #
    # SUTS 는 SwUDS(단위 설계서)를 근거로 만드는 문서다. 정본도 그렇다 — 정본 1,005
    # 함수는 SwUDS 설계 ID 1,026 과 교집합 1,001 로 사실상 일치한다(실측 2026-08-11).
    # 소스에는 그보다 많은 함수가 있고(실측 1,160), 그중 155개는 정본이 시험 대상으로
    # 삼지 않는다(부트로더 계열 등).
    #
    # ⚠ 이건 앞서 걷어낸 `docs/uds_function_swcom_override.json` 필터와 **성질이 다르다**.
    #   그건 저장소에 박힌 251개 목록이라 프로젝트가 바뀌어도 같은 걸로 잘랐다.
    #   이건 **그 프로젝트의 SwUDS 문서**가 근거이고, 문서가 없으면 필터도 걸지 않는다.
    #
    # 범위를 좁힌 사실은 **반드시 보고한다** — 조용히 자르면 커버리지가 또 자기 자신을
    # 분모로 삼게 된다.
    units, _scope_notes = apply_scope(units, scope)
    for _n in _scope_notes:
        _progress(40, _n)

    # ── HSIS signal enrichment ────────────────────────────────────────────
    # Uses HSIS xlsx to enrich: srs_req_ids (from related_id), variable
    # boundary hints from characteristics (e.g. "0...255"), and srs_req_ids
    # for units that read/write HSIS signal SW variables.
    # 파일 접근만 with 안에서 끝낸다 — 아래 가공은 메모리 데이터라 임시 파일이 필요 없다.
    _hsis_data: Optional[Dict[str, Any]] = None
    with _resolved_doc_input(hsis_path, "HSIS") as _hsis_local:
        if _hsis_local:
            _progress(38, "HSIS 신호 보강 중")
            try:
                from generators.sts import _load_hsis_signals
                _hsis_data = _load_hsis_signals(_hsis_local)
            except Exception as _hsis_exc:
                _logger.warning("HSIS 파싱 실패 — 보강 생략: %s", _hsis_exc)
                _enrich_failed("hsis_parse", _hsis_exc)
    if _hsis_data:
        try:
            _hsis_signals = _hsis_data.get("signals", [])
            if _hsis_signals:
                # Build sw_var_name → signal dict (one var can split by \n/,)
                _hsis_var_map: Dict[str, Dict[str, Any]] = {}
                for _sig in _hsis_signals:
                    _sw_raw = str(_sig.get("sw_var_name") or "")
                    for _tok in re.split(r"[\n,\s]+", _sw_raw):
                        _tok = _tok.strip()
                        if _tok and re.match(r"^[A-Za-z_]\w+$", _tok):
                            _hsis_var_map[_tok] = _sig

                # (R74 N90) 경계는 **SW 값 범위** 칸(`Value Range`, 예 `0x0000U ~ 0xFFFFU`)에서 읽는다. 예전엔
                #   `Characteristics`(`9 to 16V` — 물리 단위)를 SW 경계로 읽으려 했고, 그나마 `hsis_bounds` 는 아무도 안 읽었다.
                from generators.uds_unit_io import parse_value_range as _parse_value_range

                enriched_hsis = 0
                for unit in units:
                    # Collect all variable names used by this unit
                    # unit dict uses "input_vars"/"output_vars" (string lists),
                    # not "inputs"/"outputs" (dicts).
                    _unit_vars: List[str] = list(unit.get("input_vars") or [])
                    _unit_vars += list(unit.get("output_vars") or [])

                    _matched: List[Dict[str, Any]] = [
                        _hsis_var_map[v] for v in _unit_vars if v in _hsis_var_map
                    ]
                    if not _matched:
                        continue

                    # 1) HSIS Related ID — SW 요구(`Sw…`)면 요구 ID 로, 시스템 요구(`SyTR_…`)면 따로 적는다
                    #    (R74: 이 HSIS 의 Related ID 는 전부 `SyTR_` 라 `srs_req_ids` 에 넣으면 레벨이 섞인다).
                    _hsis_req_ids = list(dict.fromkeys(
                        str(s["related_id"]).strip() for s in _matched
                        if s.get("related_id") and str(s["related_id"]).strip()))
                    _sw_ids = [x for x in _hsis_req_ids if x.lower().startswith("sw")]
                    if _sw_ids and not unit.get("srs_req_ids"):
                        unit["srs_req_ids"] = ", ".join(_sw_ids)
                        unit["srs_req_link"] = "hsis"
                    _sy_ids = [x for x in _hsis_req_ids if not x.lower().startswith("sw")]
                    if _sy_ids:
                        unit["hsis_related_ids"] = ", ".join(_sy_ids)

                    # 2) store HSIS boundary hints on the unit for sequence generation
                    _hsis_bounds: Dict[str, tuple] = {}
                    for _vname in _unit_vars:
                        if _vname in _hsis_var_map:
                            _rng = _parse_value_range(_hsis_var_map[_vname].get("value_range", ""))
                            if _rng is not None:
                                _hsis_bounds[_vname] = _rng
                    if _hsis_bounds:
                        unit.setdefault("hsis_bounds", {}).update(_hsis_bounds)

                    enriched_hsis += 1

                _logger.info("HSIS enrichment: %d units enriched from %d signals",
                             enriched_hsis, len(_hsis_signals))
        except Exception as _hsis_exc:
            _logger.warning("HSIS enrichment skipped: %s", _hsis_exc)
            _enrich_failed("hsis_enrichment", _hsis_exc)

    if globals_info_map:
        set_globals_type_cache(globals_info_map)

    # ── Indirect variable enrichment for void/no-param functions ─────────────
    # For units with no input/output vars, derive testable variables from
    # the global variables of their callee functions (indirect side effects).
    _fn_name_to_info: Dict[str, Dict[str, Any]] = {
        info.get("name", ""): info
        for info in function_details.values()
        if isinstance(info, dict) and info.get("name")
    }
    for _void_unit in units:
        if _void_unit.get("input_vars") or _void_unit.get("output_vars"):
            continue
        _indirect: List[str] = []
        for _callee_name in (_void_unit.get("calls_list") or [])[:8]:
            _callee_info = _fn_name_to_info.get(_callee_name)
            if not _callee_info:
                continue
            # Prefer callee outputs (side effects), then inputs
            _callee_outs = _extract_var_names(_callee_info.get("outputs") or [])
            _callee_ins = _extract_var_names(_callee_info.get("inputs") or [])
            for _v in _callee_outs + _callee_ins:
                if _v not in _indirect:
                    _indirect.append(_v)
            if len(_indirect) >= 6:
                break
        if _indirect:
            _void_unit["indirect_vars"] = _indirect[:6]
            _logger.debug("void unit %s: indirect_vars=%s", _void_unit["name"], _indirect[:6])

    # ── logic_flow variable extraction for remaining void functions ──────────
    # For units still without any testable variable (calls_list was also empty),
    # extract C identifier names from logic_flow condition/text strings.
    # Filters out: C keywords, all-caps macro names, single-letter tokens.
    _C_KEYWORDS = frozenset({
        "if", "else", "while", "for", "return", "switch", "case", "break",
        "continue", "do", "null", "true", "false", "void", "int", "char",
        "uint", "uint8", "uint16", "uint32", "int8", "int16", "int32",
    })
    for _void_unit in units:
        if (_void_unit.get("input_vars") or _void_unit.get("output_vars")
                or _void_unit.get("indirect_vars")):
            continue
        _lf_vars: List[str] = []

        def _walk_flow_nodes(nodes: List[Any]) -> None:
            for _n in nodes:
                if not isinstance(_n, dict):
                    continue
                _text = str(_n.get("condition") or _n.get("text") or "")
                # Extract C identifiers from condition/text
                for _tok in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b", _text):
                    if (_tok.lower() not in _C_KEYWORDS
                            and not _tok.isupper()  # skip ALL_CAPS macros
                            and _tok not in _lf_vars
                            and len(_lf_vars) < 6):
                        _lf_vars.append(_tok)
                # Recurse into sub-bodies
                for _key in ("true_body", "false_body", "body"):
                    _sub = _n.get(_key)
                    if isinstance(_sub, list):
                        _walk_flow_nodes(_sub)

        _walk_flow_nodes(_void_unit.get("logic_flow") or [])
        if _lf_vars:
            _void_unit["indirect_vars"] = _lf_vars
            _logger.debug("void unit %s: logic_flow vars=%s", _void_unit["name"], _lf_vars)

    # Identify void functions that still lack all variable info — these are
    # the only ones that need AI enhancement (limits API calls to ~12 units).
    _void_no_vars = {
        u["fid"] for u in units
        if not u.get("input_vars") and not u.get("output_vars")
        and not u.get("indirect_vars")
    }
    _logger.info("Units needing AI enhancement: %d", len(_void_no_vars))

    _progress(40, "테스트 시퀀스 생성 시작")
    _profile, _profile_bad = normalize_tc_profile(tc_profile)
    _extended = _profile == TC_PROFILE_EXTENDED
    if _profile_bad:
        _logger.warning("SUTS: 모르는 tc_profile %r — 기본(정본 규모)으로 만든다", _profile_bad)
    all_sequences: Dict[str, List[Dict[str, Any]]] = {}
    ai_enhanced = 0
    for i, unit in enumerate(units):
        # (R19) 확장: 소스가 읽는데 입력 목록에 없는 객체를 선언 타입으로 더해 다시 만든다 — 기본 프로파일은 정본 규모라 그대로.
        seqs = extended_unit_sequences(unit) if _extended else generate_sequences(unit, max_sequences)
        if ai_config and unit["fid"] in _void_no_vars:
            seqs = enhance_sequences_with_ai(unit, seqs, ai_config)
            ai_enhanced += 1
        all_sequences[unit["fid"]] = seqs
        if (i + 1) % 50 == 0 or i == len(units) - 1:
            pct = 40 + int(35 * (i + 1) / len(units))
            _progress(pct, f"시퀀스 생성 {i+1}/{len(units)}")
    if ai_enhanced:
        _logger.info("AI enhanced %d void-function units", ai_enhanced)
    # (R21) 행이 설정하는 입력·적는 기대값을 TC 의 열로 — 문서에 없는 자극에 기댄 기대값을 남기지 않는다(두 프로파일)
    for unit in units:
        render_row_io(unit, all_sequences.get(unit["fid"]) or [])

    total_seq = sum(len(s) for s in all_sequences.values())
    _progress(80, f"시퀀스 생성 완료 - {total_seq}개")

    quality = generate_suts_quality_report(units, all_sequences, _source_function_count(function_details))
    # (R75) 어느 프로파일로 만들었나 · 확장 전략이 덧붙인 시퀀스 수(기본이면 0).
    quality["tc_profile"] = _profile
    quality["tc_profile_unknown_value"] = _profile_bad
    # (R76 N104) 세 생성기가 같은 두 키로 "요청한 상한 / 실제로 건 상한" 을 말한다(SITS 가 먼저 썼다). `None` = 상한 없음.
    quality["caps_requested"] = {"max_sequences": max_sequences}
    quality["caps_effective"] = {"max_sequences": None if _extended else max_sequences}
    quality["enrichment_errors"] = _enrich_errors
    quality["extended_sequences"] = sum(
        1 for _s in all_sequences.values() for _q in _s if _q.get("tc_profile") == TC_PROFILE_EXTENDED)
    # (R17) #if verdicts on build-configuration evidence — units, reasons, names taken as undefined
    from generators.c_project_context import summarize_build_assumptions
    quality["build_assumptions"] = summarize_build_assumptions(u.get("project_scope") for u in units)
    # (R21) 행이 설정해 열로 보인 입력·기대값(두 프로파일)
    quality["row_io_columns"] = summarize_row_io(units)
    # (R23) 입력이 앞 행과 같은 행 — 정본 규모 행은 남기고 세며, 확장 전략 행은 뺀 수
    quality["duplicate_rows"] = summarize_duplicate_rows(units)
    if _extended:
        # (R15) 행동 경계 행 — 탐색하지 못한 unit(범위 없음·정수 입력 없음·출력 없음)과 예산 소진을 분모와 함께 공시한다.
        _bsearch = [u.get("boundary_search") for u in units if isinstance(u.get("boundary_search"), dict)]
        quality["boundary_rows"] = sum(
            1 for _s in all_sequences.values() for _q in _s if str(_q.get("strategy") or "").startswith(BOUNDARY_PREFIX))
        quality["boundary_search"] = {
            "units": len(units), "searched": sum(1 for b in _bsearch if b.get("status") == "searched"),
            "with_rows": sum(1 for b in _bsearch if b.get("rows")),
            "boundaries": sum(int(b.get("boundaries") or 0) for b in _bsearch),
            "budget_exhausted": sum(1 for b in _bsearch if b.get("budget_exhausted")),
            "evaluation_budget_exhausted": sum(1 for b in _bsearch if b.get("evaluation_budget_exhausted")),
            "boundary_cap_reached": sum(1 for b in _bsearch if b.get("boundary_cap_reached")),
            # (리뷰 W1) 상한에 잘린 기준 행·상수·값 집합도 unit 수로 공시한다
            "bases_capped": sum(1 for b in _bsearch if int(b.get("bases_available") or 0) > int(b.get("bases") or 0)),
            "constants_capped": sum(1 for b in _bsearch if int(b.get("constants_capped_inputs") or 0) > 0),
            "value_sets_capped": sum(int(b.get("value_sets_capped") or 0) for b in _bsearch),
            "evaluations": sum(int(b.get("evaluations") or 0) for b in _bsearch),
            # 상태의 사유 꼬리(`oracle_underived:<reason>`)는 분포에서 떼어 종류로 센다
            "not_searched": dict(Counter(str(b.get("status")).split(":", 1)[0] for b in _bsearch
                                         if b.get("status") != "searched")),
            "units_without_search": len(units) - len(_bsearch)}
        # (R19) 소스가 읽어 더한 입력 — 설계서 입력 목록과 달라지는 열이라 분모와 사유를 함께 공시한다.
        quality["source_read_inputs"] = summarize_source_read_inputs(units)
        # (R19) MC/DC 채움 행 — 벡터가 비운 결정 무관 입력을 채운 동반 행(쌍 주장 없음)
        _fills = [u.get("mcdc_fill") for u in units if isinstance(u.get("mcdc_fill"), dict)]
        quality["mcdc_fill"] = {k: sum(int(f.get(k) or 0) for f in _fills)
                                for k in ("mcdc_rows", "rows_with_blanks", "rows", "not_fillable", "duplicates", "pruned")}
        quality["mcdc_fill"]["units_with_rows"] = sum(1 for f in _fills if f.get("rows"))
        quality["mcdc_fill"]["errors"] = sum(1 for f in _fills if f.get("error"))
    # 확장은 시퀀스 상한도 푼다 — 기본 카탈로그 안에 있었지만 상한(`max_sequences`)에 잘리던 자리가 이제 나온다.
    #   위 수와 합치면 기본 문서 대비 증분이다(입출력 없는 unit 은 전략 목록을 쓰지 않아 0).
    quality["sequences_beyond_reference_cap"] = (sum(
        max(0, min(int(_u.get("base_strategy_count") or 0), len(all_sequences.get(_u["fid"]) or [])) - int(max_sequences))
        for _u in units) if _extended else 0)

    _progress(85, "XLSM 파일 생성 중")
    out = generate_suts_xlsm(template_path, units, all_sequences, output_path, project_config)

    _progress(90, "생성 문서 자동 검증 중")
    validation = validate_suts_xlsm(out)
    # 생성 수 ↔ 파일 기록 수 대조. `validate_suts_xlsm` 에 `expected_tc_range`/
    # `expected_seq_range` 인자가 **있는데도** 호출부 4곳이 전부 기본값 None 이라
    # 그 대조는 한 번도 실행된 적이 없었다 — 정답(total_seq)이 바로 윗줄에 있는데도.
    # 판정 로직은 세 생성기 공용 단일 출처(`_artifact_check`)로 통일한다.
    validation = apply_write_back_check(validation, {
        "tc_count": len(units),
        "seq_count": total_seq,
    })
    _note_unknown_type_slots(validation, quality)
    for _err in _enrich_errors:
        validation.setdefault("warnings", []).append(
            f"설계 근거 보강 단계 `{_err['stage']}` 가 실패해 건너뛰었다 — {_err['error']}")
    if validation.get("issues"):
        _logger.warning("SUTS validation issues: %s", validation["issues"])

    validation_report_path = ""
    try:
        validation_report_path = generate_suts_validation_report(out, quality, validation=validation)
        _logger.info("SUTS validation report: %s", validation_report_path)
    except Exception as _vr:
        _logger.warning("SUTS validation report generation skipped: %s", _vr)

    elapsed = time.time() - t0
    _progress(100, f"SUTS 생성 완료 ({elapsed:.1f}초)")

    # Quality DB recording (non-fatal)
    try:
        from workflow.quality.recorder import record_run
        record_run(
            "suts", quality,
            project_root=str(source_root or ""),
            elapsed_sec=elapsed,
            output_path=out,
            ai_model=str((ai_config or {}).get("model", "")),
        )
    except Exception:
        # non-fatal 은 유지하되 침묵은 금지 (sts.py 의 동일 블록이 NameError 를
        # 몇 년간 삼켜 품질 기록이 통째로 유실된 전례).
        _logger.exception("SUTS quality record skipped (non-fatal)")

    return {
        "output_path": out,
        "quality_report": quality,
        "test_case_count": len(units),
        "total_sequences": total_seq,
        "elapsed_seconds": round(elapsed, 1),
        "validation": validation,
        "validation_report_path": validation_report_path,
    }


def _lightweight_parse(source_root: str) -> Dict[str, Dict[str, Any]]:
    """Lightweight C source parsing when full report_generator is unavailable."""
    from report.c_parsing import (
        _extract_c_definitions,
        _extract_c_function_bodies,
        _extract_simple_call_names,
        _strip_c_comments,
    )

    root = Path(source_root)
    c_files = list(root.rglob("*.c"))
    function_details: Dict[str, Dict[str, Any]] = {}
    fn_counter = 0

    for cf in c_files:
        try:
            raw = cf.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # (R62 N69) 죽은 `#if 0` 분기의 함수로 시험 케이스를 만들지 않는다 — 정식 경로(tree-sitter)와 같은 규칙.
        stripped = _strip_c_comments(blank_dead_code(raw))
        defs = _extract_c_definitions(stripped)
        bodies = _extract_c_function_bodies(stripped)

        for d in defs:
            # _extract_c_definitions returns Tuple[name, params, is_static]
            if isinstance(d, tuple):
                name = d[0] if len(d) > 0 else ""
                params = d[1] if len(d) > 1 else ""
            elif isinstance(d, dict):
                name = d.get("name", "")
                params = d.get("params", "")
            else:
                continue
            if not name:
                continue
            fn_counter += 1
            fid = f"SwUFn_{fn_counter:04d}"
            sig = f"void {name}({params})" if params else f"void {name}(void)"
            body = bodies.get(name, "")
            calls = _extract_simple_call_names(body) if body else []

            function_details[fid] = {
                "id": fid,
                "name": name,
                "prototype": sig,
                "inputs": [f"[IN] {p}" for p in _lw_parse_params(sig)],
                "outputs": _lw_parse_outputs(sig, name),
                "calls_list": calls,
                "logic_flow": _lw_extract_logic_flow(body),
                "globals_global": [],
                "globals_static": [],
                "module_name": cf.stem,
                "file": str(cf),
                "description": "",
                "asil": "TBD",
                "precondition": "",
            }

    return function_details


def _lw_parse_params(sig: str) -> List[str]:
    if "(" not in sig:
        return []
    params = sig.split("(", 1)[1].rsplit(")", 1)[0].strip()
    if not params or params.lower() == "void":
        return []
    result = []
    for p in params.split(","):
        p = p.strip()
        parts = p.split()
        if parts:
            result.append(parts[-1].strip("*&"))
    return result


def _lw_parse_outputs(sig: str, name: str) -> List[str]:
    if not sig:
        return []
    head = sig.split(name, 1)[0] if name in sig else sig
    head = re.sub(r"\b(static|extern|inline)\b", "", head).strip()
    if returns_value(head):
        return [f"[OUT] return {head.strip()}"]
    return []


_LW_BRANCH_RE = re.compile(
    r'\b(if|else\s+if|else|switch|case|for|while)\b\s*(\([^)]*\))?',
    re.IGNORECASE,
)


def _lw_extract_logic_flow(body: str) -> List[Dict[str, Any]]:
    """Extract simplified logic flow nodes from a C function body."""
    if not body:
        return []
    nodes: List[Dict[str, Any]] = []
    for m in _LW_BRANCH_RE.finditer(body):
        keyword = m.group(1).strip().lower()
        cond = (m.group(2) or "").strip("() \t")
        node: Dict[str, Any] = {"type": keyword, "text": m.group(0).strip()}
        if cond:
            node["condition"] = cond
        nodes.append(node)
        if len(nodes) >= 40:
            break
    return nodes


# ---------------------------------------------------------------------------
# Document validation
# ---------------------------------------------------------------------------

def generate_suts_validation_report(
    xlsm_path: str,
    quality_report: Optional[Dict[str, Any]] = None,
    validation: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a validation report markdown for SUTS XLSM.

    Writes a .validation.md file next to the XLSM and returns its path.
    """
    validation_data = validation if isinstance(validation, dict) else validate_suts_xlsm(xlsm_path)
    stats = validation_data.get("stats", {})
    issues = validation_data.get("issues", [])
    warnings = validation_data.get("warnings", [])
    qr = quality_report or {}

    tc_count = stats.get("tc_count", 0)
    seq_count = stats.get("seq_count", 0)
    empty_io = stats.get("empty_io_tc_count", 0)

    lines = [
        "# SUTS 생성 문서 자동 검증 리포트",
        "",
        f"**파일**: `{Path(xlsm_path).name}`  ",
        f"**검증 시각**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**결과**: {'PASS' if validation_data.get('valid') else 'FAIL'}",
        "",
        "---",
        "",
        "## 1. 구조 검증",
        "",
        "| 항목 | 값 |",
        "|------|-----|",
        f"| 시트 수 | {stats.get('sheet_count', 0)} |",
        f"| 시트 목록 | {', '.join(stats.get('sheets', []))} |",
        f"| TC 수 | {tc_count} |",
        f"| 시퀀스 수 | {seq_count} |",
        f"| TC당 평균 시퀀스 | {stats.get('avg_seq_per_tc', 0)} |",
        f"| I/O 없는 TC 수 | {empty_io} |",
        "",
    ]

    if qr:
        lines.extend([
            "## 2. 품질 지표",
            "",
            "| 항목 | 값 |",
            "|------|-----|",
            f"| 총 TC 수 | {qr.get('total_test_cases', 0)} |",
            f"| 총 시퀀스 수 | {qr.get('total_sequences', 0)} |",
            f"| TC당 평균 시퀀스 | {qr.get('avg_sequences_per_tc', 0)} |",
            f"| 총 입력 변수 | {qr.get('total_input_vars', 0)} |",
            f"| 총 출력 변수 | {qr.get('total_output_vars', 0)} |",
            f"| I/O 보유 TC | {qr.get('with_io_count', 0)} ({qr.get('io_coverage_pct', 0)}%) |",
            f"| 로직 보유 TC | {qr.get('with_logic_count', 0)} |",
            # 미측정은 `0%` 가 아니라 `—` 다. 0% 로 그리면 "한 함수도 안 덮였다" 로 읽힌다.
            "| 함수 커버리지 | "
            + (f"{qr['function_coverage_pct']}%" if qr.get("function_coverage_pct") is not None else "— (미측정)")
            + f" (소스 함수 {qr.get('total_source_functions') or '—'}개 기준) |",
            "",
        ])
        if qr.get("gen_method_distribution"):
            lines.extend([
                "### 생성 방법 분포",
                "",
                "| 방법 | 수 |",
                "|------|-----|",
            ])
            for k, v in qr["gen_method_distribution"].items():
                lines.append(f"| {k} | {v} |")
            lines.append("")

    # (R32 Q-10) TC 가 0건이면 "I/O 없는 TC 비율"·"평균 시퀀스" 는 정의되지 않는다. 예전엔 `if tc_count
    #   else True` 로 **통과**로 접어 빈 문서가 5개 중 3개를 통과했다(TC 존재·시퀀스 존재만 FAIL).
    #   해당 없음(`None`)은 분모에서 빼고 표에는 `N/A` 로 적는다 — 통과도 실패도 아니다.
    gate_items = [
        ("TC 존재", tc_count > 0),
        ("시퀀스 존재", seq_count > 0),
        ("I/O 없는 TC < 50%", (empty_io <= tc_count * 0.5) if tc_count else None),
        ("TC당 평균 시퀀스 >= 2", (stats.get("avg_seq_per_tc", 0) >= 2) if tc_count else None),
        # ⚠ 미측정(None)을 통과로 접지 않는다 — 못 잰 것을 "이상 없음" 으로 만들면
        #   게이트가 fail-open 이 된다. TC 가 있으면 그건 그것대로 별도 항목이 본다.
        ("함수 커버리지 측정됨", (qr or {}).get("function_coverage_pct") is not None),
    ]
    applicable = [(name, ok) for name, ok in gate_items if ok is not None]
    passed = sum(1 for _, ok in applicable if ok)

    lines.extend([
        f"## 3. Quality Gate ({passed}/{len(applicable)})",
        "",
        "| 항목 | 결과 |",
        "|------|------|",
    ])
    for name, ok in gate_items:
        lines.append(f"| {name} | {'N/A (TC 없음)' if ok is None else ('PASS' if ok else 'FAIL')} |")
    lines.append("")

    if issues:
        lines.extend(["## 4. Issues", ""])
        for i in issues:
            lines.append(f"- {i}")
        lines.append("")

    # ⚠ 형제 리포트(STS)에는 있는데 여기엔 절 자체가 없었다 — 검증기가 경고를
    #   만들어도 리포트에 닿을 길이 없었다는 뜻이다(그래서 아무도 안 만들었다).
    if warnings:
        lines.extend(["## 5. Warnings", ""])
        for w in warnings:
            lines.append(f"- ⚠ {w}")
        lines.append("")

    out_path = Path(xlsm_path).with_suffix(".validation.md")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return str(out_path)


def validate_suts_output(xlsm_path: str) -> Dict[str, Any]:
    """Validate a generated SUTS XLSM for structural completeness."""
    from openpyxl import load_workbook
    wb = load_workbook(xlsm_path, read_only=True, data_only=True)
    issues: List[str] = []
    warnings: List[str] = []
    stats: Dict[str, Any] = {"sheets": wb.sheetnames, "sheet_count": len(wb.sheetnames)}

    # (R77 N114 · 리뷰 W3) `validate_suts_xlsm` 과 **같은 판정**이다 — 명세 시트는 필수(issue), 나머지는 선택(warning), 이름은
    #   번호 접두 무시. 한쪽만 고치면 같은 파일을 두 검증기가 PASS/FAIL 로 갈라 말한다(형제 검증기 계약).
    _spec_sheet = _find_spec_sheet(wb.sheetnames)
    if _spec_sheet is None:
        issues.append(f"Missing sheet: {_SUTS_SPEC_SHEET}")
    _present = {_sheet_base_name(n) for n in wb.sheetnames}
    for s in ("Cover", "History", "1.Introduction", "1.Test Environment"):
        if _sheet_base_name(s) not in _present:
            warnings.append(f"Optional sheet missing: {s}")

    if _spec_sheet is not None:
        ws = wb[_spec_sheet]
        tc_count = 0
        seq_count = 0
        total_inp = 0
        total_out = 0
        tc_no_inp = 0
        tc_no_out = 0
        # ⚠ 열 번호를 하드코딩하지 않는다 — 레이아웃 상수에서 파생한다. 예전엔
        #   `range(14,63)`·`column=11` 이 박혀 있어, 레이아웃이 바뀌면 검증기가
        #   조용히 0을 세고 그 0이 "이슈 없음"으로 통과했다(fail-open).
        #
        # ⚠ `read_only=True` 에서 `ws.cell(row, col)` 랜덤 접근을 쓰지 말 것.
        #   순차 스트리밍이라 되짚으면 **빈 셀을 돌려준다**. 실측(2026-08-11):
        #   시퀀스 7,267건이 파일에 멀쩡히 있는데 검증기는 1,576건으로 셌다
        #   (-5,691). 행이 1,975 → 8,219 로 늘자 증상이 드러났다. 파일이 아니라
        #   **검증기가 틀린 것**이라, 그대로 뒀으면 정상 산출물을 결함으로 신고한다.
        #   전체 스캔은 `iter_rows` 가 유일한 정답이다
        #   (`[[reference_openpyxl_readonly_cell_perf]]` — 성능만이 아니라 정확성 문제).
        _max_col = max(_OUTPUT_COL_END, _RELATED_COL)
        for row in ws.iter_rows(min_row=_DATA_START_ROW, max_col=_max_col, values_only=True):
            tc_id = row[_COL_TC_ID - 1] if len(row) >= _COL_TC_ID else None
            if tc_id and str(tc_id).startswith("SwUTC"):
                tc_count += 1
                _n_inp = sum(
                    1 for v in row[_INPUT_COL_START - 1:_INPUT_COL_END] if v not in (None, "")
                )
                _n_out = sum(
                    1 for v in row[_OUTPUT_COL_START - 1:_OUTPUT_COL_END] if v not in (None, "")
                )
                total_inp += _n_inp
                total_out += _n_out
                # ⚠ 평균은 0 을 숨긴다. 실측(2026-08-12): 948 TC 중 **338 건이 입력 0개**인데
                #   평균은 2.0 이라 `avg_inp < 1` 게이트를 그대로 통과했다. 입력이 없는
                #   시퀀스는 시험이 성립하지 않으므로 건수를 따로 센다.
                if _n_inp == 0:
                    tc_no_inp += 1
                if _n_out == 0:
                    tc_no_out += 1
            elif len(row) >= _SEQ_COL and row[_SEQ_COL - 1] not in (None, ""):
                seq_count += 1

        stats["tc_count"] = tc_count
        stats["seq_count"] = seq_count
        stats["avg_inp"] = round(total_inp / max(tc_count, 1), 1)
        stats["avg_out"] = round(total_out / max(tc_count, 1), 1)
        stats["avg_seq"] = round(seq_count / max(tc_count, 1), 1)
        # 항상 싣는다 — 0 건이어도 키가 있어야 "재지 않았다" 와 "0 이었다" 가 구분된다.
        stats["tc_without_input"] = tc_no_inp
        stats["tc_without_expected"] = tc_no_out

        if tc_count == 0:
            issues.append("No test cases found")
        if seq_count == 0:
            issues.append("No sequences found")
        if stats["avg_inp"] < 1:
            issues.append(f"Low avg input vars: {stats['avg_inp']}")
        if stats["avg_out"] < 1:
            issues.append(f"Low avg output vars: {stats['avg_out']}")
        # 경고는 `issues` 와 분리한다 — 입력 0개 TC 는 **정상일 수도 있다**(파라미터도
        # 전역도 없는 함수. 정본도 1,005 중 172 건이 그렇다). `valid` 를 뒤집으면
        # 정상 산출물이 실패로 신고된다. 다만 숨기지도 않는다.
        if tc_count and tc_no_inp:
            warnings.append(
                f"입력 변수가 없는 TC {tc_no_inp}건 "
                f"({tc_no_inp * 100.0 / tc_count:.1f}%) — 해당 시퀀스는 실행 값이 없다"
            )
        if tc_count and tc_no_out:
            warnings.append(
                f"기대 결과가 없는 TC {tc_no_out}건 ({tc_no_out * 100.0 / tc_count:.1f}%)"
            )

    wb.close()
    stats["issues"] = issues
    stats["warnings"] = warnings
    stats["valid"] = len(issues) == 0
    return stats
