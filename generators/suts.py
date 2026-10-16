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
from generators.c_source_oracle import INITIAL_VALUE_PREFIX, UNWRITTEN_OUTPUT_PREFIX
from generators.mcdc_design import (
    SEARCH_LIMITS,
    build_mcdc_design,
    finalize_mcdc_design,
    mcdc_report_summary,
    search_limits,
)
from generators.safety_marks import resolve_safety_related as _resolve_safety_related
from generators.scenario_rows import MAX_ATOMS as _SCENARIO_MAX_ATOMS
from generators.scenario_rows import MAX_PROPAGATE_CHECK as _PROPAGATE_MAX_CHECK
from generators.scenario_rows import MAX_PROPAGATE_CHECK_RUNS as _PROPAGATE_MAX_CHECK_RUNS
from generators.scenario_rows import MAX_PROPAGATE_CHECK_STEPS as _PROPAGATE_MAX_CHECK_STEPS
from generators.scenario_rows import MAX_PROPAGATE_ROWS as _PROPAGATE_MAX_ROWS
from generators.scenario_rows import MAX_ROWS as _SCENARIO_MAX_ROWS
from generators.scenario_rows import SCENARIO_FI_PREFIX, SCENARIO_PREFIX, _at_home, find_scenarios
from generators.tc_profile import TC_PROFILE_EXTENDED, normalize_tc_profile
from generators.test_evidence import VERIFY_PREFIX, apply_sequence_evidence, summarize_expected_evidence
from generators.uds_unit_io import resolve_unit_io
from report_gen.c_return import returns_value
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
# (R85) MC/DC 는 카탈로그(`strategies`)의 맨 끝이지만 상한은 더 이상 카탈로그 앞에서 자르지 않는다 — 정본 규모 블록
#   (`_reference_scale_block`)이 MC/DC 설계 행을 **먼저** 남긴다. MC/DC 가 잘리는 것은 상한이 그 함수의 MC/DC 설계 행 수
#   (최대 `_BASE_MCDC_SLOTS`)보다 작을 때뿐이다(R85 전에는 switch 6 개면 기본값 24 에서도 MC/DC 7 → 1 이었다). ISO 26262 ASIL D 는
#   MC/DC 가 필수다 — 준비 게이트가 이 규칙으로 경고한다(`docgen_preflight._mcdc_risk`).
_DEFAULT_SEQ_COUNT = 24
_STRATEGY_CATALOG_MAX = 30
# 기본 카탈로그가 전략 종류별로 내는 **자리 수**. 생성부(`generate_sequences`)와 판별부(`is_extended_strategy`)가
# 같은 상수를 본다 — 따로 적으면 한쪽만 바뀌어도 아무것도 안 깨진 채 공시가 틀린다(R75 리뷰 X5).
_BASE_SWITCH_SLOTS = 6
_BASE_GLOBAL_SLOTS = 3
_BASE_MCDC_SLOTS = 7
# (R85) 정본 규모 문서의 행 자리. 행 수는 그대로(`min(상한, 카탈로그 수)`)이고 그 안을 이 순서로 채운다 — ① 이 이름의 카탈로그
#   행(MC/DC 설계 벡터 — 쌍 근거 · switch case · 루프 횟수 · 부수효과) ② 코드 기준 행(`CODE_` — 설계 입력만으로 원본 코드 모델이
#   문장 · 분기 결과와 결함이 드러나는 값에 한 경로로 닿는 입력, R78 · R79 와 같은 탐색) ③ 남은 카탈로그 행(전 입력 타입 경계 ·
#   조건 조합 · 전역)을 카탈로그 순서로. 실측(R85): 정본만 판별한 변이 HDPDM01 554 · KJPDS02_PV 487 중 80% · 51% 가 '정본이 쓰는
#   입력값을 생성 행이 그 입력에 한 번도 주지 않음' 이었고 그 값의 88% · 65% 가 함수 본문의 비교 상수 K · K±1 이었다 — 설계가
#   범위를 주지 않은 입력에 타입 경계값(0 · 가운데 · 끝값)만 주던 카탈로그가 코드가 그 입력을 나누는 지점을 밟지 않았다(R78 이
#   찾은 같은 원인을 그때는 확장 프로파일에만 고쳤다). 자리를 내준 카탈로그 행은 확장 문서에서 정본 규모 블록 뒤에
#   `CATALOG_<이름>` 으로 남는다(확장 행은 이름으로 가린다 — R75). 범위 밖 강건성(FI) 행 BV_MIN_INV · BV_MAX_INV 도 먼저 두는
#   행이다 — 정본 체제의 시험 방법 범주(REQ/FI)이고 ISO 26262-6 의 결함 주입 · 강건성 시험이라, 코드 기준 행이 자리를 다 가져가
#   함수에 FI 행이 하나도 남지 않으면 안 된다(실측: 그렇게 잃은 R84 정본 규모 kill 62 중 51 이 정본도 잡던 것). 상한이 좁으면
#   이 순서(MC/DC → switch → 루프 → 부수효과 → FI)로 남긴다. (리뷰 R85 W-R4-3 · W-R5-1 · W-R5-3) 범위 밖 값을 싣는 행 — FI 두 행과
#   부수효과 행(입력마다 경계+1) — 은 그 값이 입력의 타입 안일 때만 먼저 두는 행이다: 원본 코드 모델이 입력을 선언 타입 밖이라
#   거부하거나(`input_outside_declared_type`) 선언된 타입의 표 밖 값이면(설계 범위가 없는 입력의 타입 경계 ±1 — U8 256 · U16
#   65536 —, 설계 하한 0 인 부호 없는 입력의 −1) 하네스에 실을 수 없고 기대값도 서지 않는다; 그런 행은 채움 후보(입력이 같은 행과
#   같은 마지막 단계)다. 추측한 타입으로는 거부하지 않는다(`_fits_type` 과 같은 규칙 — 거부권은 근거에만).
CODE_PREFIX = "CODE_"
CATALOG_PREFIX = "CATALOG_"
_REFERENCE_KEEP = ("MCDC_", "SWITCH_", "LOOP_", "VOID_SIDE_EFFECT", "BV_MIN_INV", "BV_MAX_INV")
# (리뷰 R85 W-R5-3) the kept rows that carry values outside the design — the FI rows and the side-effect row (every input at its
#   boundary plus one): kept only when the values are inputs the harness can hold, and no covered rows of the code search
_REFERENCE_KEEP_OUTSIDE = frozenset({"BV_MIN_INV", "BV_MAX_INV", "VOID_SIDE_EFFECT"})
_REFUSED_INPUT = "input_outside_declared_type:"

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

# (R52 N39) `_merge_sds_partition_map` 은 `report_gen.requirements` 단일 출처 — UDS 세 경로와 같은 first-wins 규칙.


def read_sds_input(sds_docx_path: Optional[str], *,
                   skipped: str = "") -> Tuple[Dict[str, Dict[str, str]], Dict[str, Any]]:
    """(R66) 지정한 SDS 문서의 파티션 맵(ASIL · Related · 설명)과 그 **판독 기록** — SUTS · SITS · STS · 영향도 카드가 이 하나를 부른다.

    ## 저장소 `docs/` 로 대체하지 않는다 (감사 #62 · #63 · #83)

    예전엔 SDS 를 주지 않았거나 못 읽거나 파티션이 0 이면 세 생성기가 저장소 `docs/` 의 SDS(`_load_default_sds_map` — 이
    저장소에 든 HDPDM01 문서)로 넘어갔다. KJPDS02_PV 를 SRS · SwUDS 만 주고 만들면(R66 실측) SUTS unit 113 개가 HDPDM01
    SDS 의 ASIL 을 받았고(그중 17 개는 PV 자기 SDS 와 등급이 다르다) STS 요구-함수 링크 8,049 개가 HDPDM01 파티션에서
    나왔다 — 요구 ID(`SwTR_0101`)는 프로젝트끼리 겹쳐 걸러지지도 않는다(114 개는 PV SDS 로는 생기지 않는 링크). 다른
    프로젝트 문서로 안전 등급과 추적성을 채우는 것은 'ASIL 지어내기 금지'(사용자 결정 2026-08-01) 위반이다. 없거나 못
    읽으면 빈 맵이고, 판독 기록이 품질 리포트 → 공시로 간다.

    입력은 resolver 경유(`_resolved_doc_input`)라 cloudium worker 전용 경로도 연다.

    Args:
        skipped: 호출자(라우트)가 지정된 경로를 로컬화하지 못한 사유(`input_skips` 의 ``SDS: …``). 경로가 없는데 이 값이
            있으면 '지정했지만 열지 못함' 이다 — '주지 않음' 으로 적으면 원인은 파일인데 안내가 '주라' 가 된다(R50 HSIS 와
            같은 규칙).

    Returns:
        ``(map, reading)`` — reading 은 ``{"given", "opened", "read", "entries", "name", "reason"}``(이름은 파일 이름만).
    """
    raw = str(sds_docx_path or "").strip()
    reading: Dict[str, Any] = {"given": bool(raw or skipped), "opened": False, "read": False, "entries": 0,
                               "name": Path(raw).name if raw else "", "reason": ""}
    if not raw:
        reading["reason"] = str(skipped or "")[:200]
        return {}, reading
    merged: Dict[str, Dict[str, str]] = {}
    opened: Dict[str, Any] = {}
    with _resolved_doc_input(raw, "SDS", report=opened) as local:
        if not local:
            reading["reason"] = str(opened.get("reason") or "열지 못함")
        else:
            reading["opened"] = True      # (리뷰 2차) 열었지만 파티션 0 과 못 연 것을 공시 안내가 가른다
            try:
                _merge_sds_partition_map(merged, _extract_sds_partition_map(local))
            except Exception as exc:  # noqa: BLE001 — docx 파서 예외가 광범위. 사유는 기록 · 공시한다
                _logger.warning("SDS 파티션 맵 판독 실패 — ASIL · 요구 연결 보강 없음: %s (%s)", raw, exc)
                reading["reason"] = f"파티션 표 판독 실패 ({type(exc).__name__})"
                merged = {}
            if not merged and not reading["reason"]:
                import zipfile
                reading["reason"] = ("docx 로 열 수 없음(zip 아님)" if not zipfile.is_zipfile(local)
                                     else "파티션 표 0 개 — SDS 양식이 다르거나 SDS 가 아닌 문서")
    reading["entries"] = len(merged)
    reading["read"] = bool(merged)
    if merged:
        _logger.info("SDS 파티션 %d건 로드 — 출처=%s", len(merged), reading["name"])
    else:
        _logger.warning("SDS 를 지정했으나 쓰지 못함(%s) — 저장소 docs/ 로 대체하지 않는다: %s", reading["reason"], raw)
    return merged, reading


#: 사유 속 경로(드라이브 · UNC) — 문서 확장자까지(공백 든 폴더 · 파일 이름 포함), 없으면 공백 전까지
#   (리뷰 2차 I1) 드라이브 앞이 글자면 경로가 아니다(`http://h:8765/…`), 지연 부분은 `:` 를 넘지 않는다(다음 경로까지 먹지
#   않게), 확장자 뒤가 영숫자면 확장자가 아니다(`b.docx와` 는 끝, `b.docxy` 는 아님)
_PATH_IN_REASON = re.compile(
    r"(?<![A-Za-z])(?:[A-Za-z]:[\\/]|\\\\)(?:[^\n:]*?\.(?:docx|doc|xlsx|xlsm|xls|pdf|txt)(?![A-Za-z0-9_])|[^\s,;()]*)",
    re.IGNORECASE)


def input_skip_reason(input_skips: Any, label: str) -> str:
    """(R66) 라우트가 넘긴 ``"<라벨>: <사유>"`` 목록에서 그 라벨의 사유(없으면 ``""``) — 라벨은 대소문자 무시, 첫 것.

    (리뷰 Info) 라우트 사유는 접근 검사 · 워커 예외 문자열을 그대로 담아 전체 경로가 들 수 있다 — 공시까지 가므로 경로는
    파일 이름만 남긴다(`_resolved_doc_input` 의 사유 규칙과 같게)."""
    want = str(label or "").strip().lower()
    for s in input_skips or ():
        head, sep, tail = str(s).partition(":")
        if sep and head.strip().lower() == want:
            return _PATH_IN_REASON.sub(lambda m: Path(m.group(0).rstrip("\\/")).name or "…", tail.strip())[:200]
    return ""


def input_document_usable(doc: str, rec: Any) -> bool:
    """(R66 리뷰 W3 · R69) 입력 문서 기록이 '쓸 수 있었다' 인가 — SDS 는 파티션을 읽었을 때, 그 밖은 열었고 생성기가 센 양이 0 이
    아닐 때: SRS 요구 수(`requirements`), SITS 의 SwUDS 함수 중 소스와 맞은 수(`functions`), SITS 의 STP 글자 수(`read_chars`).
    세지 않았으면(키 없음) 연 것으로 본다. 공시 · 검증 경고 · '보강 실패 0건' 문구가 같은 판정을 쓴다.

    ⚠ 이 세 키는 '이 문서에서 생성기가 쓴 양' 이라는 계약이다 — 다른 뜻의 수를 같은 이름으로 기록에 넣으면 판정이 조용히 바뀐다."""
    if not isinstance(rec, dict):
        return False
    if doc == "SDS":
        return bool(rec.get("read"))
    # (R69) 읽은 것을 센 문서(SRS 요구 · SwUDS 함수 · STP 글자)는 그 수가 0 이면 쓸 수 없었다 — 세지 않았으면(None) 연 것으로 본다
    return bool(rec.get("opened")) and all(rec.get(k) != 0 for k in ("requirements", "functions", "read_chars"))


def note_input_document(docs: Dict[str, Dict[str, Any]], doc: str, path: Optional[str], block: str,
                        opened: Dict[str, Any], input_skips: Any = None) -> Dict[str, Any]:
    """(R66, 감사 #1) 입력 문서 하나의 열기 기록을 ``docs[doc]`` 에 모은다 — ``{"given", "opened", "name", "reason",
    "blocks_unopened"}``.

    같은 문서를 여러 블록이 열면(SUTS 는 SwUDS 를 입출력 · 설명/설계 ID · 설계 ID 브리지로 세 번) 하나라도 못 열었으면
    ``opened`` 는 거짓이고 그 블록 이름이 남는다 — 그 블록이 채웠을 값(설계서 범위 · 요구 ID 등)이 이 문서에 없다. 경로가
    없는데 라우트가 그 라벨의 사유를 넘겼으면(`input_skips`) '지정했지만 열지 못함' 이다. ``opened`` 는 블록마다
    `_resolved_doc_input(report=…)` 가 적은 dict."""
    raw = str(path or "").strip()
    rec = docs.setdefault(doc, {"given": False, "opened": False, "name": "", "reason": "", "blocks_unopened": []})
    skip = input_skip_reason(input_skips, doc)
    if raw and skip:
        # (리뷰 2차 I5) 라우트가 지정 문서를 못 열고 다른 파일(요구 문서 목록의 SRS 등)을 넘겼다 — 그 사실을 남긴다
        rec["specified_unopened"] = skip
    if raw:
        first = not rec["given"]
        rec["given"] = True
        rec["name"] = rec["name"] or Path(raw).name
        ok = bool(opened.get("opened"))
        rec["opened"] = ok if first else (rec["opened"] and ok)
        if not ok:
            rec["blocks_unopened"].append(block)
            rec["reason"] = rec["reason"] or str(opened.get("reason") or "열지 못함")
        return rec
    if skip:
        rec["given"] = True
        rec["opened"] = False
        rec["reason"] = rec["reason"] or skip
        if block not in rec["blocks_unopened"]:
            rec["blocks_unopened"].append(block)
    return rec


def input_documents_record(paths: Dict[str, Optional[str]], input_skips: Any = None) -> Dict[str, Dict[str, Any]]:
    """(R66) SITS · STS 처럼 라우트가 로컬화한 경로를 생성기가 그대로 여는 입력의 기록(`note_input_document` 와 같은 꼴).

    경로가 있으면 로컬 파일로 열 수 있는지, 없으면 라우트가 넘긴 그 라벨의 사유를 본다. 문서를 읽은 내용(요구 수 · 파티션
    수)은 호출자가 덧붙인다 — `requirements` · `functions` · `read_chars` 는 `input_document_usable` 이 판정에 쓰는 키다(그 뜻으로만)."""
    docs: Dict[str, Dict[str, Any]] = {}
    for doc, path in paths.items():
        raw = str(path or "").strip()
        ok = False
        if raw:
            try:
                ok = Path(raw).is_file()
            except OSError:
                ok = False
        note_input_document(docs, doc, path, "generator_input",
                            {"opened": ok, "reason": "" if ok else "파일 없음 — 넘겨받은 경로를 열 수 없다"}, input_skips)
    return docs


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


def _object_is_const(name: str, gim: Optional[Dict[str, Dict[str, str]]]) -> bool:
    """(R67) 객체 **자체**가 `const` 인가 — `const U8 tab[9]` · `U8 * const p` 는 그렇고, `const U8 *p` 는 아니다(포인터는 시험이
    설정하는 입력이고 const 는 가리키는 곳의 것). `_is_const_global` 은 `const` 낱말만 봐서 둘을 가르지 않는다 — 소스 루프의 그
    판정은 그대로 두고, 설계서가 적은 입력을 빼는 자리(아래 `_const_in`)는 이 판정을 쓴다(정당한 포인터 입력을 지우지 않게)."""
    t = str(((gim or {}).get(name) or {}).get("type") or "")
    if "*" in t:
        return bool(re.search(r"\*[^*]*\bconst\b[^*]*$", t))
    return is_const_type(t)


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
        sds_map: ASIL 보강에 쓸 SDS 파티션 맵(`read_sds_input`). None 이면 빈 맵이다 — (R66) 저장소 `docs/` 의 다른
            프로젝트 SDS 로 대체하지 않는다. SwUDS · 소스 `@asil` · SDS 어디에도 근거가 없는 unit 의 ASIL 은 `TBD`.
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
    sds_map = sds_map or {}
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
        _uds_const_in: List[str] = []
        if _uds_rec is not None:
            # ⚠ UDS 는 반환값을 `Return` 으로, 정본 SUTS 는 `return` 으로 적는다.
            #   대소문자만 다른 같은 것이라 그대로 두면 **한 행에 반환값이 두 번**
            #   실리고 그중 하나는 정본에 없는 이름이 된다(실측 284칸 = 이 축 신규
            #   과다의 85%). 표기는 `_RETURN_VAR` **한 곳**으로 모은다.
            def _norm_uds(x: str) -> str:
                y = _vc_pointer_notation(x)
                return _RETURN_VAR if y.strip().lower() == _RETURN_VAR else y

            _u_in = [_norm_uds(x) for x in (_uds_rec.get("inputs") or []) if x]
            # (R67) the design's own spelling of each input — ``->`` (a path through a pointer) is gone after `_norm_uds`
            _u_in_raw = {_norm_uds(x): str(x) for x in reversed(_uds_rec.get("inputs") or []) if x}
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
                # (R67, audit #45) a const object the design lists as an input — KJPDS02_PV `g_DrvIn_MotorSpeed` lists the
                #   lookup table `static const U8 u8s_ShiftBitLut[9]`: its rows set nine ROM elements no test can set (the
                #   oracle reads the declaration's values anyway), the same thing the source loop above leaves out
                #   (`_is_const_global` — the reference SUTS writes no const global). A parameter of the name is no global;
                #   a pointer to const (`const U8 *p`) is a settable pointer — `_object_is_const`.
                _const_in = [x for x in input_vars if (_r := re.split(r"[\[.]", x, maxsplit=1)[0]) not in _param_roots
                             and _object_is_const(_r, gim)
                             # (review round 3 I-3) ``U8 * const p``: ``p[0]`` is what p points to — writable
                             and (x == _r if "*" in str((gim.get(_r) or {}).get("type") or "")
                                  # a member or element of the const object is the object (``s_NTCLookupTable.u16_AdcValue``,
                                  #   KJPDS02_PV); a path the design wrote through ``->`` reaches writable data
                                  else "->" not in _u_in_raw.get(x, x))]
                if _const_in:
                    input_vars = [x for x in input_vars if x not in _const_in]
                    inp_set = set(input_vars)
                    _uds_const_in = _const_in
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
        # (R66 리뷰 2차 W-B) 저장소 override 스냅샷(프로젝트 확인 없음)의 등급이 **최종 등급을 정한** unit — SwUDS 가 없거나 더
        #   낮을 때. 근거 라벨 `uds+override` 만으로는 스냅샷이 등급을 올렸는지 구별되지 않는다(공시가 이 수를 말한다)
        _asil_by_override = bool(_src_kind == "override" and _src_grade and asil == _src_grade and _src_grade != _uds_grade)
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
            "asil_by_override": _asil_by_override,
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
            # (R67) inputs the design lists that the source declares const — not set by any row (`summarize_uds_const_inputs`)
            "uds_const_inputs": _uds_const_in,
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


def _holds_declared_types(inputs: Dict[str, Any], var_types: Dict[str, str], declared: Any) -> bool:
    """(R85 리뷰 W-R4-3) 행의 값이 모두 그 입력의 선언 타입이 담는 값인가 — 카탈로그가 값을 만든 같은 타입 표(`get_boundary_values`)로
    본다. 설계 범위가 없는 입력의 범위 밖 FI 값은 타입 경계 ±1(U8 256 · U16 65536)이라 하네스에 실을 수 없다. (리뷰 R85 W-R5-1)
    타입이 **선언에서 온** 입력(`declared`)만 거부한다 — 추측한 타입(이름 패턴 · `uint8_t` 기본값)으로 거부하면 원본 코드 모델이
    받는 행(선언 U16 의 1201)을 밀어낸다(`_fits_type` 과 같은 규칙). 정수 폭 타입은 표의 범위로, bit · bool 은 음수만(밑 타입이 더
    넓을 수 있어 0x2 는 담을 수 있다 — `unsigned char`), enum · 설계 범위 타입 · 모르는 타입 · 실수 · 정수로 읽히지 않는 값은
    담는다고 본다(지어내지 않는다 — 원본 코드 모델의 판정이 따로 본다, `_oracle_refused_inputs`)."""
    declared = set(declared or ())
    for v, x in inputs.items():
        if v not in declared:
            continue
        t = str(var_types.get(v) or "")
        if t == "float":
            continue
        if isinstance(x, str):
            try:
                x = int(x, 0)
            except ValueError:
                continue
        if not isinstance(x, int) or isinstance(x, bool):
            continue
        if t in ("bit", "bool"):
            if x < 0:
                return False
            continue
        tb = get_boundary_values(t)
        lo, hi = tb.get("min"), tb.get("max")
        if isinstance(lo, int) and isinstance(hi, int) and not lo <= x <= hi:
            return False
    return True


def _oracle_refused_inputs(unit: Dict[str, Any], rows: List[Dict[str, Any]], outputs: List[str]) -> List[bool]:
    """(리뷰 R85 W-R5-1) 행마다 원본 코드 모델이 입력을 선언 타입 밖이라 거부했는가(`input_outside_declared_type`, 그 입력을 읽은
    경로에서만 보인다) — 모델이 쓰는 선언 타입(scope)으로 본다: 설계 범위 타입(`T_Tmr`) · bool 의 −1 처럼 생성기의 타입 표가 모르는
    것도. 모델을 돌릴 수 없으면(소스 · scope 없음, 관측할 출력 없음) 거부하지 않았다고 본다."""
    if not rows or not outputs or not isinstance(unit.get("project_scope"), dict):
        return [False] * len(rows)
    from generators.c_source_oracle import evaluate_outputs
    runs = evaluate_outputs(unit, rows, [list(outputs)] * len(rows))
    return [_REFUSED_INPUT in str(run.get("reason") or "")
            or any(_REFUSED_INPUT in str((o or {}).get("reason") or "") for o in (run.get("outputs") or {}).values())
            for run in runs]


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
    # (R65, 감사 #18) 설계서는 포인터 멤버를 `p->m` 으로 적고 unit 이름은 정본 표기 `p[0].m` 이다 — 둘 다 `->` 를 `.` 로,
    #   첨자를 뗀 같은 열쇠로 맞춘다(KJPDS02_PV 301 · HDPDM01 49 행이 예전엔 한 번도 조회되지 않았다)
    canon: Dict[str, Dict[str, Any]] = {}
    for k, v in info.items():
        canon.setdefault(_uds_param_key(str(k)), v)
    out: Dict[str, Dict[str, Any]] = {}
    for v in names:
        for key in (v, re.sub(r"\[[^\]]*\]", "", v)):
            rec = info.get(key) or lowered.get(key.lower())
            if isinstance(rec, dict) and rec:
                out[v] = rec
                break
        else:
            rec = canon.get(_uds_param_key(v))
            if isinstance(rec, dict) and rec:
                out[v] = rec
    return out


def _source_function_names(function_details: Dict[str, Any]) -> List[str]:
    """소스에서 찾은 함수 이름(SwUDS 표 Name 행 별칭을 거르는 데 쓴다 — `restrict_aliases`)."""
    return [str((v or {}).get("name") or "") for v in (function_details or {}).values() if isinstance(v, dict)]


def _uds_param_key(name: str) -> str:
    """(R65) 설계서 파라미터 이름과 unit 이름이 같은 객체인지 보는 열쇠 — `p->m` · `p[0].m` · `p.m` 이 같다."""
    return re.sub(r"\[[^\]]*\]", "", name.replace("->", ".")).replace(" ", "").lower()


def summarize_source_read_failures(block: Any, units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """(R68, 감사 #16) 소스 단계가 끝내 읽지 못한 파일(`generate_uds_source_sections` 의 `source_read_failures` — 파일 이름 ·
    실패 종류)과 그 때문에 원문 없이 남은 unit(`source_unavailable_reason = source_read_failed:<종류>`). 품질 리포트
    `source_read_failures`."""
    block = block if isinstance(block, dict) else {}
    hit = [str(u.get("name") or "") for u in units
           if str(u.get("source_unavailable_reason") or "").startswith("source_read_failed:")]
    return {"files": int(block.get("files") or 0), "kinds": dict(block.get("kinds") or {}),
            "lost": dict(block.get("lost") or {}),
            # (리뷰 4차 W1) 주 스캔이 놓친 헤더 — 그 주석에서 오는 다른 파일 함수의 ASIL · 설명이 TBD 일 수 있다(공시가 이름을 댄다)
            "headers_scan_missed": [str(x) for x in (block.get("headers_scan_missed") or [])][:10],
            "detail": [d for d in (block.get("detail") or []) if isinstance(d, dict)][:10],
            "units": len(hit), "unit_samples": hit[:8]}


def summarize_uds_const_inputs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """(R67, audit #45) 설계서가 입력으로 적었지만 소스가 `const` 로 선언한 객체 — 어느 행도 그 값을 설정하지 않는다(시험이 설정할
    수 없는 ROM 이고 oracle 은 선언의 값을 쓴다). 품질 리포트 `uds_const_inputs`."""
    hit = [(str(u.get("name") or ""), [str(x) for x in (u.get("uds_const_inputs") or [])])
           for u in units if u.get("uds_const_inputs")]
    return {"units": len(hit), "names": sum(len(n) for _u, n in hit),
            "samples": [f"{u}: {', '.join(n[:3])}" for u, n in hit[:5]]}


def summarize_uds_reading(io_map: Optional[Dict[str, Any]], units: List[Dict[str, Any]], given: bool,
                          source_functions: Any = None) -> Dict[str, Any]:
    """(R65) SwUDS 를 어떻게 읽었나(품질 보고서 `uds_reading` — 공시 `suts_uds_reading` 이 읽는다).

    문서 수준(`load_uds_unit_io` 의 `reading`: 머리말 · 표 · 표시 붙은 머리말 · 삭제 표시 · 표 `Name` 별칭 · 파라미터 행 ·
    세로 병합으로 이어진 행 · 이름으로 못 읽은 행 · Value Range 판독) + 이 문서의 unit 에 닿은 것(표시 붙은 머리말 · 별칭으로
    찾은 unit, 값 목록을 쓴 변수, 설계서가 적었지만 읽지 못한 범위의 변수 — 사유별).
    """
    if not given:
        return {"given": False}
    from generators.uds_design_ids import read_design_heading

    r = dict((io_map or {}).get("reading") or {})
    out: Dict[str, Any] = {"given": True, "read": bool((io_map or {}).get("by_name"))}
    for k in ("read_error", "headings", "tables", "functions", "ambiguous", "param_rows", "rows_continued", "range_read",
              "values_read", "range_unread_by_reason", "range_unread_samples", "range_notation", "deleted_headings",
              "alias_conflicts", "unread_headings", "superseded_headings"):
        if k in r:
            out[k] = r[k]
    # 별칭은 **쓴 것**만 적는다(리뷰 R65 2차 N3 — 소스에 둘 다 있어 뺀 별칭을 '찾는다' 고 공시했다)
    from generators.uds_design_ids import checked_aliases

    out["name_row_aliases"] = [f"{h} ← 표 Name `{a}`" for a, h in sorted(checked_aliases(io_map).items())]
    out["alias_dropped_source"] = list((io_map or {}).get("alias_dropped_source") or [])
    # 문서는 삭제했는데 소스에는 있는 함수 — 시험 범위(SwUDS 기반)에서 빠진다. 같은 이름의 살아 있는 머리말이 매핑됐으면
    #   (`(삭제)` + `(New)` 짝) 빠지지 않는다 — 그 이름은 빼고 센다(리뷰 R65 3차 V1)
    _src = {str(x).lower() for x in (source_functions or ()) if x}
    _mapped = {str(k).lower() for k in ((io_map or {}).get("by_name") or {})} \
        | {str(a).lower() for a in checked_aliases(io_map)} \
        | {str(n).lower() for n in (r.get("live_heading_names") or [])}
    out["deleted_in_source"] = sorted({h["name"] for t in (r.get("deleted_headings") or [])
                                       for h in [read_design_heading(t)]
                                       if h and h["name"].lower() in _src and h["name"].lower() not in _mapped})
    out["marked_headings"] = len(r.get("marked_headings") or [])
    out["marked_heading_samples"] = list((r.get("marked_headings") or [])[:5])
    out["rows_unread"] = len(r.get("rows_unread") or [])
    out["rows_unread_samples"] = list((r.get("rows_unread") or [])[:8])
    names = {str(u.get("name") or "") for u in units}
    # 표시 붙은 머리말 중 이 문서의 unit 이 **실제로 그 표를 받은** 것만(동명이인 · 표 없는 머리말은 뺀다 — 리뷰 R65 I6)
    _tabled = set((io_map or {}).get("by_name") or {})
    marked = [h["name"] for t in (r.get("marked_headings") or []) for h in [read_design_heading(t)] if h]
    out["units_via_marked_heading"] = sorted(n for n in marked if n in names and n in _tabled)
    out["units_via_name_row_alias"] = sorted(a for a in checked_aliases(io_map) if a in names)
    why: Dict[str, int] = {}
    samples: List[str] = []
    values_vars = 0
    for u in units:
        for v, reason in (u.get("uds_range_unread") or {}).items():
            why[str(reason)] = why.get(str(reason), 0) + 1
            if len(samples) < 8:
                _txt = ((u.get("uds_param_info") or {}).get(v) or {}).get("range_text") or ""
                samples.append(f"{u.get('name')}.{v} `{_txt}`")
        values_vars += sum(1 for s in (u.get("bounds_source") or {}).values() if s == "uds_values")
    out["unit_vars_range_unread"] = why
    out["unit_vars_range_unread_samples"] = samples
    out["unit_vars_uds_values"] = values_vars
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


def _uds_value_bounds(rec: Any) -> Dict[str, Any]:
    """(R65) 설계서 Value Range 의 **값 목록**(`0, 5, 15` — 연속이 아닌 집합) → 열거자와 같은 경계값 dict(최소 · 가운데 ·
    최대는 목록의 값 그대로, 범위 밖 ±1). 두 값 이상일 때만 — 값 하나는 범위로 읽지 않는다(`read_value_range`)."""
    vals = (rec or {}).get("values") if isinstance(rec, dict) else None
    if not isinstance(vals, list) or len(vals) < 2:
        return {}
    return enum_bounds({"values": vals})


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
    """확장 프로파일에서만 나오는 전략인가 — OAT·경계(BND)·MC/DC 채움 행(R19)·설계 범위 밖 강건성 행(R31)·동작 시나리오
    행(R78) 전부, 그리고 기본 자리 수를 넘는 SWITCH(6+)·GLOBAL(3+)·MCDC(7+). (R85) 정본 규모 문서에서 코드 기준 행에 자리를
    내준 카탈로그 행(`CATALOG_<이름>`)도 — 코드 기준 행(`CODE_`)은 정본 규모 행이다."""
    s = str(strategy or "").strip()
    if s.startswith(("OAT_", BOUNDARY_PREFIX, MCDC_FILL_PREFIX, ROBUST_PREFIX, OBS_MCDC_PREFIX, SCENARIO_PREFIX,
                     SCENARIO_FI_PREFIX, STUB_APART_PREFIX, PROPAGATE_PREFIX, PROPAGATE_FI_PREFIX, CATALOG_PREFIX)):
        return True
    for prefix, base_n in (("SWITCH_", _BASE_SWITCH_SLOTS), ("GLOBAL_", _BASE_GLOBAL_SLOTS), ("MCDC_", _BASE_MCDC_SLOTS)):
        if s.startswith(prefix) and s[len(prefix):].isdigit():
            return int(s[len(prefix):]) >= base_n
    return False


def _boundary_domains(unit: Dict[str, Any], input_vars: List[str], var_types: Dict[str, str],
                      var_bounds: Dict[str, Dict[str, Any]], unknown_vars: set,
                      enum_sets: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """입력마다 움직일 수 있는 정수 도메인 — `(lo, hi)` 범위 또는 enum 열거자 목록(R15 경계 행·R19 MC/DC 채움 행 공용).
    모르는 타입·부동소수·경계 미상은 싣지 않는다(값을 지어내지 않는다). `enum_sets`: 시퀀스 생성이 쓴 값 집합(R40 — 포인터
    대상의 열거자까지; 없으면 `unit["value_domains"]`)."""
    enum_sets = enum_sets if enum_sets is not None else (unit.get("value_domains") or {})
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
            elif (unit.get("bounds_source") or {}).get(v) == "uds_values":
                _design = set(((unit.get("uds_param_info") or {}).get(v) or {}).get("values") or [])
                vals = [x for x in vals if x in _design]
            if len(vals) >= 2:
                domains[v] = vals
            continue
        if (unit.get("bounds_source") or {}).get(v) == "uds_values":
            # (R65) 설계서가 적은 값 목록 — 목록 사이의 정수는 설계가 정한 값이 아니다(열거자와 같은 규칙, 리뷰 C2)
            try:
                vals = sorted({int(x) for x in (((unit.get("uds_param_info") or {}).get(v) or {}).get("values") or [])})
            except (TypeError, ValueError):
                vals = []
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
                          unknown_vars: set, enum_sets: Optional[Dict[str, Any]] = None) -> None:
    """(R15) 행동 경계 행 — `generators.boundary_rows.find_boundaries` 가 소스 oracle 로 찾은 인접 입력 쌍을 시퀀스 뒤에 붙인다.

    움직일 수 있는 입력은 정수 경계가 정해진 것만(모르는 타입·부동소수·경계 미상 제외 — 값을 지어내지 않는다). enum 은
    **열거자 값 집합**으로 넘긴다 — 열거자 사이의 정수는 쓰지 않는다(리뷰 C2). 기준 행 후보는 전 입력 중간값(BV_MID) → MC/DC
    설계 벡터 → 조건 조합 → 나머지 순으로 넘기고, 후보가 상한보다 많으면 탐색기가 한 번씩 돌려 **서로 다른 출력 상태**·도출
    출력이 많은 행을 먼저 쓴다(이 순서는 동률일 때만). 도메인 밖 값을 가진 행(BV_*_INV)은 기준이 아니다. 기대값은 여기서 적지 않는다: 붙인 뒤
    같은 oracle(`apply_sequence_evidence`)이 모든 행과 똑같이 도출한다. 탐색 요약은 `unit["boundary_search"]` 에 남는다.
    탐색이 실패해도 문서는 만든다 — 그 unit 만 경계 행 없이 두고 사유를 남긴다(리뷰 C1).
    """
    domains = _boundary_domains(unit, input_vars, var_types, var_bounds, unknown_vars, enum_sets)
    outputs = list(dict.fromkeys([*output_vars, *(k for s in _search_rows(sequences) for k in (s.get("expected") or {}))]))

    # (R78) 동작 시나리오 행은 기준 행 순위에 끼지 않고 **더한** 기준이다(`extra_bases`) — 기존 기준 행의 탐색은 그 행들이 없을
    #   때와 같다(첫 판에서 순위 맨 앞에 두자 기존 기준이 밀려 경계 6개를 잃었다 — R4b 와 같은 교훈: 옮기지 말고 더한다)
    order = _base_order([s for s in _search_rows(sequences) if not _is_scenario(s)])
    scenarios = _base_order([s for s in _search_rows(sequences) if _is_scenario(s)])
    # 행이 비운 입력의 채움 값 — BV_MID 와 같은 중간값에서 출발한다(넓은 범위면 입력마다 위치만큼 옮겨 서로 다르게, enum 은 열거자).
    mids = {v: (var_bounds.get(v) or {}).get("mid") for v in domains}
    defaults = {v: m for v, m in mids.items() if isinstance(m, int) and not isinstance(m, bool)}
    try:
        from generators.boundary_rows import blank_fill
        # (review R82 I-R5-2) a write's prior value keeps off the value the function writes there in these rows too
        overrides = _prior_fill_overrides(unit, blank_fill(domains, defaults), domains, var_bounds)[0]
        found = find_boundaries(
            unit, [{"inputs": s.get("inputs") or {}, "strategy": s.get("strategy")} for s in order], domains, outputs,
            [s.get("inputs") or {} for s in _search_rows(sequences)],
            defaults=defaults, fill_overrides=overrides,
            extra_bases=[{"inputs": s.get("inputs") or {}, "strategy": s.get("strategy")} for s in scenarios])
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


# (R31) 설계 범위 밖 강건성 행 — 설계서·HSIS 가 입력 범위를 정했는데(`uds_range`/`hsis_range`) 함수 본문이 그 입력을 범위
#   **밖이면서 선언 타입 안**인 상수와 직접 비교하면(`u16s_Tm < u16g_MAX`, 설계 범위 0~60), 코드가 그 값을 다룬다는 뜻이다 —
#   정본 시험자는 그 경계(0xFFFE·0xFFFF)를 FI 로 적었고, 경계 행(R15)은 설계 범위 안에서만 움직여 거기 닿지 않았다
#   (R26 측정: 정본만 판별한 변이 KJPDS02_PV 280 중 150 · HDPDM01 285 중 19 가 생성 스위트가 쓰는 값 범위 밖의 입력을
#   요구했다). 코드 상수에서 나온 경계값 분석이지 변이에서 나온 값이 아니다. 기대값은 다른 행과 같은 oracle 이 도출한다(타입 밖
#   값은 행으로 만들지 않는다 — oracle 도 실행 불가 입력으로 거부한다).
ROBUST_PREFIX = "ROBUST_"
MAX_ROBUST_ROWS = 12          # unit 당 — 넘으면 자르고 센다
MAX_ROBUST_BASES = 6          # 비교가 살아 있는 기준 행을 찾을 후보 수(비교마다 후보 × 4 점 평가)
MAX_ROBUST_SCENARIO_BASES = 6  # (R78) 그 뒤에 더하는 동작 시나리오 행 후보 수
# unit 보고서와 품질 집계가 같은 키를 쓴다(리뷰 2라운드 W2-D: 집계 튜플에서 키 하나가 빠지면 공시 문장이 조용히 사라진다)
ROBUSTNESS_REPORT_KEYS = (
    "inputs_with_design_range", "inputs_type_unconfirmed", "inputs_no_type_width", "inputs_shadowed", "body_unread",
    "compared_constants_outside_design", "constants_outside_type", "live", "not_live", "no_base", "unprobed",
    "underived", "macro_argument_live", "macro_argument_unconfirmed", "undecided_preprocessor_blocks", "rows", "cut",
    "duplicates")


def summarize_robustness_rows(units: List[Dict[str, Any]]) -> Dict[str, int]:
    """(R31) unit 보고서 합계 + 상한 · 행이 생긴 unit · 실패 unit — 품질 보고서 `robustness_rows`(생성 공시가 읽는다)."""
    reports = [u.get("robustness_rows") for u in units if isinstance(u.get("robustness_rows"), dict)]
    out = {k: sum(int(r.get(k) or 0) for r in reports) for k in ROBUSTNESS_REPORT_KEYS}
    out.update(cap_per_unit=MAX_ROBUST_ROWS, units_with_rows=sum(1 for r in reports if r.get("rows")),
               errors=sum(1 for r in reports if r.get("error")))
    return out


def _catalogue_position(seq: Dict[str, Any]) -> Optional[int]:
    """(리뷰 R85 W1 · I-7) 정본 규모 카탈로그 자리의 번호 — `generate_sequences` 가 행을 만든 자리에서 단다
    (`catalogue_slot`, 기본 자리만; 이름으로 되읽지 않는다 — R75 '표시는 만든 자리에서'). 확장 자리 · 카탈로그 밖 행은 None."""
    slot = seq.get("catalogue_slot")
    return slot if isinstance(slot, int) and not isinstance(slot, bool) else None


def _base_order(sequences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """기준 행 후보 순서(`_base_rank`) — 동률은 정본 규모 카탈로그 행이 카탈로그 순서로 먼저, 나머지는 문서 순서(R15 경계 ·
    R31 강건성 · R60 출력 관측 쌍 공용)."""
    def key(item: Tuple[int, Dict[str, Any]]) -> tuple:
        pos, s = item
        cat = _catalogue_position(s)
        return (_base_rank(s), 0 if cat is not None else 1, cat if cat is not None else 0, pos)
    return [s for _pos, s in sorted(enumerate(sequences), key=key)]


def _base_rank(s: Dict[str, Any]) -> int:
    """기준 행 후보 순서 — 전 입력 중간값(BV_MID) → MC/DC 설계 벡터 → 조건 조합 → 나머지 → 동작 시나리오(R78, 맨 뒤)(R15 경계
    행·R31 강건성 행·R60 출력 관측 쌍 공용). (R78) 동작 시나리오 행은 기존 기준의 순위를 밀지 않는다 — 경계 탐색 · 강건성 행은
    그 행들을 기존 기준 **뒤에 더한** 기준으로 쓴다(`extra_bases` · `MAX_ROBUST_SCENARIO_BASES`)."""
    name = _catalog_name(s.get("strategy"))
    if _is_scenario(s):
        return 5
    return 0 if name == "BV_MID" else 1 if name.startswith("MCDC_") else 2 if name.startswith("COND_COMB_") else 3


def _search_rows(sequences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """(R85) 확장 탐색이 보는 행 — 정본 규모 코드 기준 행(`CODE_`)을 빼고 R85 전의 순서로(카탈로그 행은 카탈로그 순서 ·
    나머지는 문서 순서). 코드 기준 행은 정본 규모 문서의 행이다: 확장의 탐색(동작 시나리오 · 경계 · 강건성 · 출력 관측 쌍 · 설계
    범위 밖 · 피호출 값 구별 · 결함 전파 · 소스가 읽는/쓰는 입출력 보완)은 그 행이 없을 때처럼 돌고, 코드 기준 행은 더해지기만
    한다(R80 교훈 — 새 탐색을 기존 탐색에 섞자 kill 을 잃었다; R85 실측: 코드 기준 행을 이미 있는 · 덮인 행으로 보자 HDPDM01
    확장 문서가 kill 34 를 잃었다 — 시나리오 행 · 경계 행이 줄었다)."""
    rows = [(i, s) for i, s in enumerate(sequences) if not str(s.get("strategy") or "").startswith(CODE_PREFIX)]

    def key(item: Tuple[int, Dict[str, Any]]) -> tuple:
        slot = _catalogue_position(item[1])
        return (0, slot) if slot is not None else (1, item[0])
    return [s for _i, s in sorted(rows, key=key)]


def _scenario_rows_first(sequences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """탐색 출발 행 순서 — 동작 시나리오 행(`SCN_` · `SCNR_`, R78 I-R3-1 · R84 I-R2-4: 서로 다른 동작 값이 더 나은 출발점) →
    나머지. 받는 행은 `_search_rows` 의 보기다 — 정본 규모 코드 기준 행은 확장 탐색에 들어오지 않는다(리뷰 R85 I-R4-2: 그래서
    이 함수 · `_is_scenario` · `_base_rank` 는 코드 기준 행을 다루지 않는다)."""
    return [s for s in sequences if _is_scenario(s)] + [s for s in sequences if not _is_scenario(s)]


def _is_scenario(s: Dict[str, Any]) -> bool:
    """(R78) 동작 시나리오 행 — 설계 범위 안(`SCN_`)과 설계 범위 밖 FI(`SCNR_`) 둘 다."""
    return str(s.get("strategy") or "").startswith((SCENARIO_PREFIX, SCENARIO_FI_PREFIX))


# (R78) 동작 시나리오 행 — unit 보고서와 품질 집계가 같은 키를 쓴다(R31 W2-D 와 같은 이유: 집계에서 키 하나가 빠지면 공시가 조용히 준다).
#   `outside_design_*` 는 설계 범위 밖 2차 탐색(`_append_scenario_fi_rows`)의 몫이다(리뷰 R78 W2: 2차 탐색의 실행 · 상한 · 중복이
#   집계에서 빠졌다)
SCENARIO_REPORT_KEYS = ("targets", "statements", "branches", "reached_clean", "reached_unclean_only", "not_reached",
                        "local_best", "climb_cap", "budget_cut", "runs", "steps", "rows", "cut", "duplicates",
                        "pools_capped", "inputs", "inputs_needed", "starts_capped", "conditions_outcome_only",
                        "outside_design_inputs", "outside_design_searched", "outside_design_reached",
                        "outside_design_rows", "outside_design_in_range_rows", "outside_design_runs",
                        "outside_design_steps", "outside_design_cut", "outside_design_duplicates",
                        "outside_design_not_reached", "outside_design_pools_capped", "outside_design_starts_capped",
                        "outside_design_value_sets", "outside_design_enum_inputs", "outside_design_enum_rows",
                        "outside_design_enum_searched", "outside_design_enum_at_range_end",
                        "outside_design_enum_type_unresolved", "outside_design_enum_reached",
                        "outside_design_enum_not_reached", "outside_design_enum_in_range_rows", "outside_design_enum_runs",
                        "outside_design_enum_steps", "outside_design_enum_cut", "outside_design_enum_duplicates",
                        "outside_design_enum_pools_capped", "outside_design_enum_starts_capped",
                        "outside_design_enum_single_value",
                        # (R79) 결함이 드러나는 값 목표(경계 · 쓰기 · 연산) — 따로 센다(자기 예산 · 행 상한)
                        "expose_targets", "expose_boundary", "expose_write", "expose_arith", "expose_covered_before",
                        "expose_reached", "expose_rows", "expose_not_reached", "expose_cut", "expose_unmodeled",
                        "expose_local_best", "expose_budget_cut", "expose_runs", "expose_steps", "expose_duplicates",
                        "reached_by_exposing_rows", "expose_refused", "expose_error_cut", "expose_met_by_reach_rows",
                        # (R82) writes whose replaced value alone was unknown: named as a prior value · not namable
                        "expose_prior_value_needed", "expose_prior_value_unnamed",
                        # (R83) pointer members the rows name by themselves, held at one value in the search
                        "harness_member_inputs")


def summarize_scenario_rows(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """(R78) unit 보고서 합계 + 탐색한 unit · 행이 생긴 unit(두 탐색 중 하나라도) · 예산 소진(두 탐색) · 실패 · 탐색하지 않은
    사유 분포 — 품질 보고서 `scenario_rows`(생성 공시가 읽는다)."""
    reports = [u.get("scenario_rows") for u in units if isinstance(u.get("scenario_rows"), dict)]
    out: Dict[str, Any] = {k: sum(int(r.get(k) or 0) for r in reports) for k in SCENARIO_REPORT_KEYS}
    out.update(units=len(units), searched=sum(1 for r in reports if r.get("status") == "searched"),
               units_with_rows=sum(1 for r in reports if r.get("rows") or r.get("outside_design_rows")
                                   or r.get("outside_design_in_range_rows") or r.get("expose_rows")
                                   or r.get("outside_design_enum_rows") or r.get("outside_design_enum_in_range_rows")),
               budget_exhausted=sum(1 for r in reports if r.get("budget_exhausted")
                                    or r.get("outside_design_budget_exhausted")
                                    or r.get("outside_design_enum_budget_exhausted")),
               expose_budget_exhausted=sum(1 for r in reports if r.get("expose_budget_exhausted")),
               errors=sum(1 for r in reports if r.get("error") or r.get("outside_design_error")),
               # (review R80 W-R4-1) the enum search failed alone — the unit keeps the other searches' rows
               enum_errors=sum(1 for r in reports if r.get("outside_design_enum_error")),
               expose_errors=sum(1 for r in reports if r.get("expose_error")),
               # (review R80 I-R5-2) a first search without inputs, then the enum search over a one-value design input
               enum_only_searched=sum(1 for r in reports if r.get("status") != "searched"
                                      and r.get("outside_design_enum_status") == "searched"),
               not_searched=dict(Counter(str(r.get("status")).split(":", 1)[0] for r in reports
                                         if r.get("status") not in ("searched", None) and not r.get("error")
                                         and r.get("outside_design_enum_status") != "searched")),
               cap_per_unit=_SCENARIO_MAX_ROWS, atoms_cap=_SCENARIO_MAX_ATOMS)
    return out


def _scenario_domains(unit: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """(R78) 동작 시나리오 탐색이 움직일 입력 — 경계 행과 같은 도메인(`_boundary_domains`, 선언 타입 · 열거자만 — 추측 타입
    금지) + 피호출 stub 반환값(`F() return`, MC/DC 와 같은 `_stub_return_domain`) + 전역 배열 원소(`g_a[1]`) · 포인터 매개변수
    대상(`p[0].a`)(MC/DC 원소 · 대상 그룹과 같은 판정: 선언 원소 · 멤버 타입, volatile 은 입력 아님, 설계 범위 적용). 나머지
    입력은 비운다."""
    from generators import c_project_context as _cpc
    from generators.mcdc_design import (
        _apply_design_range,
        _element_input,
        _pointee_input,
        _pointer_member_input,
        _scope_domain,
        _stub_return_domain,
    )
    var_types = ctx["var_types"]
    declared = set(ctx.get("declared") or ())
    domains: Dict[str, Any] = {
        v: d for v, d in _boundary_domains(unit, ctx["input_vars"], var_types, ctx["var_bounds"], set(ctx["unknown"]),
                                           ctx.get("enum_sets")).items()
        if var_types.get(v) == _ENUM_TYPE or v in declared}
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    own = str(unit.get("name") or "")
    for v in ctx["input_vars"] if scope else ():
        if v in domains:
            continue
        if str(v).endswith(f"() {_RETURN_VAR}"):
            d = _stub_return_domain(v, scope, own)
            if d:
                domains[v] = d
            continue
        if _pointer_member_input(scope, own, v):
            # (R83) a pointer member the rows name by itself (`ReqMsg[0].data`): a row that sets it has the harness give
            #   that member a buffer (R82), so the search runs with it too — one value, the design middle the other rows
            #   put there (KJPDS02_PV `sf_LinUdsSecurityAccess`: without it `&ReqMsg->data[2]` was through an unknown
            #   pointer — a possible UB on every SendKey path — and the search reached them only uncleanly, so no row)
            #   (review R83 I5) only where the rows put a value — a member of unknown type stays blank there and here
            mid = (ctx.get("var_bounds", {}).get(v) or {}).get("mid")
            if isinstance(mid, int) and not isinstance(mid, bool) and v not in set(ctx.get("unknown") or ()):
                domains[v] = {"values": [mid], "harness_member": True}
            continue
        found = _element_input(scope, v)
        kind = ("array_element_declaration", "global") if found is not None else None
        if found is None:
            found = _pointee_input(scope, own, v)
            kind = ("pointee_declaration", "parameter") if found is not None else None
        if found is None or kind is None or found[2]:
            continue
        try:
            d = _scope_domain(found[0], found[1], scope, kind[0], origin=kind[1])
        except _cpc.Unresolved:
            continue
        _apply_design_range(unit, v, d)
        domains[v] = d
    return domains


def _scenario_outputs(ctx: Dict[str, Any], sequences: List[Dict[str, Any]]) -> List[str]:
    return list(dict.fromkeys([*ctx["output_vars"], *(k for s in sequences for k in (s.get("expected") or {}))]))


def _scenario_row(sequences: List[Dict[str, Any]], row: Dict[str, Any], strategy: str, outputs: List[str],
                  var_types: Dict[str, str], outside: Dict[str, int], span: Dict[str, tuple],
                  enums: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
    enums = enums or {}
    inputs = {k: _format_test_value(v, var_types.get(k, "uint8_t")) for k, v in row["inputs"].items()}
    kind = row["target_kind"]
    seen = row.get("exposure") or [None, None]
    if kind == "branch":
        what = f"분기 {row['target_line']}행 `{row['target_text']}` → {'참' if row['target_outcome'] else '거짓'}"
    elif kind == "boundary":
        # (R79) 결함이 드러나는 값 — 경계: 두 값이 같을 때 평가되고 그 조건이 결정을 가른다(`>` · `>=` 가 갈림)
        what = (f"경계 {row['target_line']}행 `{row['target_text']}` 를 두 값이 같을 때(비교하는 타입으로 바꾼 값 "
                f"{seen[0]} = {seen[1]}) 평가하고 이 조건이 결정을 가른다")
    elif kind == "write":
        what = f"쓰기 {row['target_line']}행 `{row['target_text']}` 가 이전 값 {seen[0]} 을 다른 값 {seen[1]} 로 바꾼다"
    elif kind == "arith":
        what = (f"연산 {row['target_line']}행 `{row['target_text']}` 의 `{row.get('operator') or ''}` 를 결과가 연산자에 "
                f"민감한 피연산자(연산하는 타입으로 바꾼 값 {seen[0]}, {seen[1]} — 0 아닌 피연산자 · 나눗수의 0 아닌 배수)로 "
                "계산한다")
    else:
        what = f"문장 {row['target_line']}행 `{row['target_text']}`"
    if outside and set(outside) & set(enums):
        # (R80) 열거자 범위 밖 값 — 이름 붙은 열거자가 아닌 값(깨진 · 초기화 안 된 상태)
        # every outside key is a value-set input here — the enum search widens nothing else (review R80 I-R4-6)
        shown = ", ".join(f"{k}={x}({_outside_label(enums[k], x)})" for k, x in list(outside.items())[:3] if k in enums)
        head = (f"열거자 밖 값 동작 시나리오: {what} 에 닿는 행 — 앞의 탐색이 닿지 못한 목표를 값 목록 입력(enum · 상태값)만 그 "
                "열거자 전부(설계가 범위 · 값 목록을 정했으면 설계 밖 열거자도)와 열거자 범위 ±1(이름 붙은 열거자가 아닌 값 — "
                "깨진 · 초기화 안 된 상태)로 넓혀 찾았고(설계 범위 입력은 설계 범위 안에서만 움직였다), 목표가 계속 닿는 한 home"
                f"(설계가 둔 값 · 열거자)으로 되돌린 뒤 남은 값: {shown}. 원본 코드 모델 실행에서 한 경로로(미정 분기 · 미정의 "
                "동작 없이) 닿는다(FI · ")
    elif outside:
        shown = ", ".join(f"{k}={x}(설계 {span[k][0]}~{span[k][1]} 밖)" for k, x in list(outside.items())[:3])
        head = (f"설계 범위 밖 동작 시나리오: {what} 에 닿는 행 — 설계 범위 안 값의 탐색이 닿지 못한 목표를 그 입력의 선언 타입 "
                f"범위로 넓혀 찾았고, 목표가 계속 닿는 한 설계 범위 안으로 되돌린 뒤 남은 값: {shown}. 원본 코드 모델 실행에서 "
                "한 경로로(미정 분기 · 미정의 동작 없이) 닿는다(FI · ")
    elif kind in ("boundary", "write", "arith"):
        head = (f"결함이 드러나는 값 시나리오: {what} — 원본 코드 모델 실행에서 한 경로로(미정 분기 · 미정의 동작 없이) "
                "그 값에 닿는다. 그 자리의 값(조건의 참 · 거짓 · 연산 결과 · 저장 값)이 그 자리의 결함으로 달라지는 값이다 — "
                "출력까지 드러나는지는 이 탐색이 보장하지 않는다(실제 실행이 가른다; 경계 · 쓰기 · 연산 값 — 변이는 만들지도 "
                "보지도 않는다 · ")
    else:
        head = (f"동작 시나리오: {what} 에 닿는 행 — 원본 코드 모델 실행에서 한 경로로(미정 분기 · 미정의 동작 없이) "
                "닿는다. 값은 코드가 비교하는 상수와 그 이웃 · switch 라벨 · 설계 범위 · 작은 0 아닌 값에서 골랐다(")
    sequences.append({
        "seq_num": len(sequences) + 1, "inputs": inputs,
        "expected": {o: f"{VERIFY_PREFIX} scenario" for o in outputs},
        "strategy": strategy, "tc_profile": TC_PROFILE_EXTENDED,
        "description": head + (f"이 행으로 처음 만족한 결함 노출 목표 {row.get('exposures_met', 0)}개 · "
                               if kind in ("boundary", "write", "arith") else "")
        + f"이 행으로 처음 닿은 문장 · 분기 결과 {row['targets_reached']}개 · 소스 oracle 탐색 · 미실행)",
        "scenario": {**{k: row[k] for k in ("target_kind", "target_line", "target_text", "target_outcome",
                                            "targets_reached")}, "outside_design": dict(outside),
                     **({"exposure": row.get("exposure"), "operator": row.get("operator")}
                        if row["target_kind"] in ("boundary", "write", "arith") else {})},
    })


def _append_scenario_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]], ctx: Dict[str, Any]) -> None:
    """(R78, 확장 프로파일) 동작 시나리오 행 — `generators.scenario_rows.find_scenarios` 가 원본 코드 모델 실행에서 본문의 문장과
    분기 결과마다 **한 경로로**(미정 분기 없이) · 미정의 동작 없이 닿는 입력을 설계 범위 안에서 찾아 시퀀스 뒤에 더한다. 값은
    코드가 비교하는 상수와 그 이웃 · switch 라벨 · 설계 범위 · 작은 0 아닌 값에서 고르고 타입 끝값은 마지막이다(HD 정본만 판별
    200 의 원인: 생성 행이 0 · 타입 가운데 · 끝값 기준이라 경로가 닫히거나 산술이 넘치거나 0 이 변화를 가렸다). 입력은
    `_scenario_domains`. 기대값은 여기서 적지 않는다 — 붙인 뒤 같은 oracle 이 도출한다. 기존 행과 입력이 같으면 더하지 않는다.
    '닿음' 은 문서에 남는 행(더한 행 · 입력이 같은 기존 행)이 닿는 것만이다 — 상한에 잘린 행의 목표는 닿지 않은 것으로 남고, 설계
    범위 밖 2차 탐색은 그 행들을 포함한 시퀀스 전체가 닿는 목표를 다시 찾지 않는다(리뷰 R78 W1). 요약은 `unit["scenario_rows"]`
    (키 `SCENARIO_REPORT_KEYS`)."""
    var_types = ctx["var_types"]
    domains = _scenario_domains(unit, ctx)
    outputs = _scenario_outputs(ctx, _search_rows(sequences))
    found = find_scenarios(unit, domains, outputs, [s.get("inputs") or {} for s in _search_rows(sequences)])
    # the second search's keys are there from the start — a unit it skips reports 0, not nothing
    unit["scenario_rows"] = {**found["report"], **dict.fromkeys(
        [k for k in SCENARIO_REPORT_KEYS if k.startswith("outside_design_")], 0),
        "harness_member_inputs": sum(1 for d in domains.values() if isinstance(d, dict) and d.get("harness_member"))}
    for i, row in enumerate(found["rows"]):
        _scenario_row(sequences, row, f"{SCENARIO_PREFIX}{i}", outputs, var_types, {}, {})


# (R85) 정본 규모 문서의 코드 기준 행 — 보고서 키(unit 기록과 품질 집계가 같은 키를 쓴다; 키 하나가 빠지면 공시가 조용히 준다)
REFERENCE_CODE_REPORT_KEYS = ("budget", "catalogue", "kept", "rows", "fill", "found", "cut", "cut_expose", "displaced",
                              "same_as_catalogue", "reached_unclean_only", "cut_reached", "cut_exposed",
                              "targets", "reached_clean", "not_reached", "covered_before", "expose_targets",
                              "expose_reached", "expose_covered_before", "runs", "steps", "expose_runs", "expose_steps",
                              # (리뷰 R85 W-R4-3) FI rows not kept first: a value past its declared type
                              "fi_out_of_type",
                              # (리뷰 R85 W-R4-1) extended rows whose inputs are a code row's (the extension searches as if
                              #   the code rows were not there)
                              "extension_same_inputs")
_EXPOSE_KINDS = ("boundary", "write", "arith")


def _code_rows(unit: Dict[str, Any], kept: List[Dict[str, Any]], ctx: Dict[str, Any], room: int,
               added_fill: Dict[str, Any], prior: frozenset = frozenset()
               ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    """(R85) 코드 기준 행 — 설계 입력만으로(`ctx` 의 입력 · 출력이 설계 목록) 동작 시나리오 탐색(`find_scenarios`, R78 의 문장 ·
    분기 결과 + R79 의 결함이 드러나는 값 — 경계 · 쓰기 · 연산)을 돌려, 먼저 둔 카탈로그 행(`kept`)이 이미 닿은 목표는 빼고
    찾은 행을 앞에서부터 `room` 개 — `(행, 탐색 보고서, 자리가 없어 넣지 못한 탐색 행)`. 두 프로파일이 같은 행을 갖도록 입력 ·
    도메인 · 출력 · 출발 행이 모두 설계 목록 위다(MC/DC 설계와 같은 규칙 — 확장 문서는 정본 규모 문서의 행을 같은 값으로 담는다,
    R75). 확장의 회차(R19)마다 같은 탐색이므로 unit 에 결과를 둔다(`_code_rows_cache`). ``added_fill``: 확장에서 더한 입력의
    고정값 — 다른 카탈로그 행과 같은 규칙(R19); ``prior``: 그중 쓰기 전 값으로만 더한 입력(R82 — 행 설명이 따로 적는다).
    먼저 둔 범위 밖 값 행(FI · 부수효과 — `_REFERENCE_KEEP_OUTSIDE`)은 출발 행이지만 덮인 행은 아니다(리뷰 R85 I-R4-1 · W-R5-3) —
    범위 밖 값으로만 닿은 목표도 설계 범위 안에서 닿는 행을 찾는다(요구 기반 REQ 행 — FI 행은 강건성 시험이지 그 목표의 정상
    동작 시험이 아니다)."""
    domains = _scenario_domains(unit, ctx)
    outputs = list(ctx["output_vars"])
    existing = [{k: v for k, v in (s.get("inputs") or {}).items() if k in domains} for s in kept]
    covered = [view for s, view in zip(kept, existing, strict=True) if str(s.get("strategy") or "") not in _REFERENCE_KEEP_OUTSIDE]
    key = (repr(sorted(domains.items(), key=lambda kv: kv[0])), repr(existing), repr(covered), tuple(outputs))
    cache = unit.get("_code_rows_cache")
    if isinstance(cache, tuple) and len(cache) == 2 and cache[0] == key:
        found = cache[1]
    else:
        found = find_scenarios(unit, domains, outputs, existing, covered=covered)
        unit["_code_rows_cache"] = (key, found)
    taken = found["rows"][:max(0, room)]
    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(taken):
        made: List[Dict[str, Any]] = []
        _scenario_row(made, row, f"{CODE_PREFIX}{i}", outputs, ctx["var_types"], {}, {})
        seq = made[0]
        seq.pop("tc_profile", None)
        seq["code_row"] = seq.pop("scenario")
        seq["description"] = "코드 기준 행(정본 규모 · 설계 입력만): " + str(seq.get("description") or "")
        fixed = {v: x for v, x in added_fill.items() if v not in seq["inputs"]}
        if fixed:
            seq["inputs"].update(fixed)
            read = [f"{v}={x}" for v, x in fixed.items() if v not in prior]
            wrote = [f"{v}={x}" for v, x in fixed.items() if v in prior]
            if read:
                seq["description"] += "\n소스가 읽어 더한 입력(설계서 입력 표 밖 · 이 행에선 고정값): " + ", ".join(read)
            if wrote:
                # (review R85 I4) the function writes these, it does not read them — as the catalogue rows say (R82)
                seq["description"] += "\n쓰기 전 값(함수가 쓰는 객체의 호출 전 값 · 이 행에선 고정값): " + ", ".join(wrote)
        rows.append(seq)
    return rows, found["report"], list(found["rows"][len(taken):])


_DISPLACED_NOTE = "정본 규모 문서에 들지 못한 카탈로그 행(행 수 상한 · 코드 기준 행에 자리를 내줌) — "


def _reference_scale_block(unit: Dict[str, Any], sequences: List[Dict[str, Any]], base_n: int, budget: int,
                           ctx: Dict[str, Any], extended: bool, added_fill: Dict[str, Any],
                           cap: Optional[int] = None, prior: frozenset = frozenset(),
                           fixed_of: Optional[Dict[int, frozenset]] = None) -> List[Dict[str, Any]]:
    """(R85) 정본 규모 블록 — 카탈로그 행(`sequences[:base_n]`, 카탈로그 순서)에서 `_REFERENCE_KEEP` 이름의 행을 먼저(예산
    안에서 — 고르는 것은 그 이름 순서(MC/DC → switch → 루프 → 부수효과 → 선언 타입 안 FI), 놓는 것은 카탈로그 순서), 남은
    자리에 코드 기준 행(`_code_rows`), 그래도 남으면 나머지 카탈로그 행을 — 아직 어느 행도 값을 주지 않은 입력을 움직이는 행 →
    다른 행과 입력이 다른 행 → 입력이 같은 행 · 선언 타입 밖 값의 FI 행 순으로, 각각 카탈로그 순서(리뷰 R85 W2: 간접 전역의
    유일한 자극인 GLOBAL 행보다 중복 행이 남았다) — 둔다. 행 수는 `budget`(정본 규모 문서의 행 수)을 넘지 않는다. 정본 규모 문서는 이
    블록이고, 확장 문서는 이 블록 뒤에 들지 못한 카탈로그 행(`CATALOG_<이름>`, 확장 표시) · 확장 카탈로그 행(`sequences[base_n:]`)을
    둔다 — 확장 문서의 앞 `len(블록)` 행이 정본 규모 문서다(R75 포함 관계; 두 호출이 같은 `budget` 일 때 — 리뷰 R85 C1).
    코드 기준 탐색이 실패하면 그 unit 은 예전처럼 카탈로그 행으로 채운다(사유를 남긴다). 행 번호는 여기서 다시 매긴다 — 번호를
    적는 단계(중복 행 · MC/DC 쌍 확정)보다 앞이다. ``cap``: 확장 호출이 상한을 주면(`generate_sequences(..., max_seq,
    extended=True)`) 예전처럼 카탈로그 부분을 앞에서 그 수만 둔다. ``prior``: 쓰기 전 값으로만 더한 입력(행 설명).
    ``fixed_of``: 행(id) → 그 행에 확장이 고정값으로 붙인 더한 입력(R19) — 블록의 판정(같은 행인가 · 새 입력인가)은 그 입력을
    뺀 **정본 규모 문서의 보기**로 한다: 두 프로파일이 같은 블록을 고르게(리뷰 R85 C-R2-1 — 고정값이 붙은 BV_MIN 은 고정값이
    없는 MC/DC 행과 달라 보여 확장에서만 뽑혔다). 코드 기준 행은 `added_fill` 의 입력이 고정값이다."""
    base_rows, ext_rows = sequences[:base_n], sequences[base_n:]
    budget = max(0, budget)   # (리뷰 R85 I-9) a cap of 0 or below is no room, not a negative one
    fixed_of = fixed_of or {}
    added = frozenset(added_fill)

    def view_key(s: Dict[str, Any], code_row: bool = False) -> str:
        drop = added if code_row else fixed_of.get(id(s), frozenset())
        return json.dumps({k: v for k, v in (s.get("inputs") or {}).items() if k not in drop}, sort_keys=True, default=str)

    def view_inputs(s: Dict[str, Any], code_row: bool = False) -> set:
        drop = added if code_row else fixed_of.get(id(s), frozenset())
        return {k for k in (s.get("inputs") or {}) if k not in drop}
    def keep_rank(i: int) -> Tuple[int, int]:
        name = str(base_rows[i].get("strategy") or "")
        return (next(r for r, fam in enumerate(_REFERENCE_KEEP) if name.startswith(fam)), i)
    var_types = ctx.get("var_types") or {}
    # (리뷰 R85 W-R4-3 · W-R5-1 · W-R5-3 · I-R5-5) a row with values outside the design is kept first only when they are
    #   inputs the harness can hold: the oracle refused none and no declared type is exceeded — judged on the reference-scale
    #   view (the extension's fixed added inputs dropped), so both profiles choose the same block
    outside = [i for i, s in enumerate(base_rows) if str(s.get("strategy") or "") in _REFERENCE_KEEP_OUTSIDE]
    views = [{k: v for k, v in (base_rows[i].get("inputs") or {}).items() if k in view_inputs(base_rows[i])}
             for i in outside]
    try:
        refused = _oracle_refused_inputs(unit, views, list(ctx.get("output_vars") or []))
    except Exception as exc:  # noqa: BLE001 — the oracle never raises; a failure here keeps the declared-type rule only
        _logger.warning("SUTS 범위 밖 값 행 판정 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        refused = [False] * len(outside)
    out_of_type = {i for i, view, r in zip(outside, views, refused, strict=True)
                   if r or not _holds_declared_types(view, var_types, ctx.get("declared"))}
    keep = sorted(sorted((i for i, s in enumerate(base_rows)
                          if str(s.get("strategy") or "").startswith(_REFERENCE_KEEP) and i not in out_of_type),
                         key=keep_rank)[:budget])
    room = max(0, budget - len(keep))
    record: Dict[str, Any] = {**dict.fromkeys(REFERENCE_CODE_REPORT_KEYS, 0), "budget": budget,
                              "catalogue": len(base_rows), "kept": len(keep), "status": "no_room", "error": "",
                              "budget_exhausted": False, "fi_out_of_type": len(out_of_type)}
    code: List[Dict[str, Any]] = []
    if room and ctx["input_vars"]:
        try:
            code, rep, cut_rows = _code_rows(unit, [base_rows[i] for i in keep], ctx, room, added_fill, prior)
            # (review R85 W3) the search's own status — a unit it could not search is not 'searched'
            record["status"] = str(rep.get("status") or "unknown")   # (리뷰 R85 I-5) no status is not success
            for k in ("targets", "reached_clean", "not_reached", "reached_unclean_only", "covered_before", "expose_targets",
                      "expose_reached", "expose_covered_before", "runs", "steps", "expose_runs", "expose_steps"):
                record[k] = int(rep.get(k) or 0)
            record["found"] = len(code) + len(cut_rows)
            record["cut"] = len(cut_rows)
            record["cut_expose"] = sum(1 for r in cut_rows if r.get("target_kind") in _EXPOSE_KINDS)
            # (review R85 W4) a target only a row left out first reached is not reached by the document (a later row
            #   reaching it too is counted with the cut row — the count errs low)
            # (review R85 W-R3-3) … and gets its own count, so that reached + unclean-only + not reached + cut-reached
            #   is every target again
            record["cut_reached"] = sum(int(r.get("targets_reached") or 0) for r in cut_rows)
            record["cut_exposed"] = sum(int(r.get("exposures_met") or 0) for r in cut_rows)
            record["reached_clean"] = max(0, record["reached_clean"] - record["cut_reached"])
            record["expose_reached"] = max(0, record["expose_reached"] - record["cut_exposed"])
            record["budget_exhausted"] = bool(rep.get("budget_exhausted") or rep.get("expose_budget_exhausted"))
        except Exception as exc:  # noqa: BLE001 — the document keeps its catalogue rows; the unit records why
            _logger.warning("SUTS 정본 규모 코드 기준 행 실패(%s): %s", unit.get("name"), exc, exc_info=True)
            record["status"] = "error"
            record["error"] = type(exc).__name__
            code = []
    elif room:
        record["status"] = "no_design_inputs"
    kept = set(keep)
    # a code row equal to a catalogue row (the search found the catalogue's own vector — HDPDM01: `BV_MID` of two
    #   design ranges) gives its place to that row: the same targets, and the catalogue row keeps its role (BV_MID is the
    #   first base of the boundary · robustness rows) and its name
    by_key: Dict[str, int] = {}
    for i, s in enumerate(base_rows):
        if i not in kept:
            by_key.setdefault(view_key(s), i)
    same: List[int] = []
    distinct: List[Dict[str, Any]] = []
    for row in code:
        i = by_key.get(view_key(row, True))
        if i is not None and i not in same:
            same.append(i)
        else:
            distinct.append(row)
    code = distinct
    for j, row in enumerate(code):
        row["strategy"] = f"{CODE_PREFIX}{j}"
    kept |= set(same)
    record["same_as_catalogue"] = len(same)
    seen = {view_key(base_rows[i]) for i in kept} | {view_key(s, True) for s in code}
    given = set().union(*(view_inputs(base_rows[i]) for i in kept), *(view_inputs(s, True) for s in code))
    left = max(0, room - len(code) - len(same))
    fill: List[int] = []
    rest = [i for i in range(len(base_rows)) if i not in kept]
    for stage in (0, 1, 2):
        for i in rest:
            if len(fill) >= left:
                break
            if i in fill:
                continue
            row_inputs = view_inputs(base_rows[i])
            # (리뷰 R85 W-R4-3) an FI row past its types derives nothing — with the rows that repeat another row's inputs
            if stage < 2 and (view_key(base_rows[i]) in seen or i in out_of_type):
                continue
            if stage == 0 and not row_inputs - given:
                continue
            fill.append(i)
            seen.add(view_key(base_rows[i]))
            given |= row_inputs
    chosen = kept | set(fill)
    block = [base_rows[i] for i in sorted(chosen)] + code
    displaced = [base_rows[i] for i in range(len(base_rows)) if i not in chosen]
    record["rows"] = len(code)
    record["fill"] = len(fill)
    record["displaced"] = len(displaced)
    out = block
    if extended:
        for s in displaced:
            s["strategy"] = CATALOG_PREFIX + str(s.get("strategy") or "")
            s["tc_profile"] = TC_PROFILE_EXTENDED
            s["description"] = _DISPLACED_NOTE + str(s.get("description") or "")
        out = block + displaced + ext_rows
    if cap is not None:
        out = out[:cap]
    for i, s in enumerate(out):
        s["seq_num"] = i + 1
    unit["reference_code_rows"] = record
    return out


def profile_increment(all_sequences: Dict[str, List[Dict[str, Any]]],
                      extended: bool) -> Tuple[int, int]:
    """(R85) 기본 문서 대비 확장 문서의 증분 `(확장 전략 행, 정본 규모 블록에 들지 못한 카탈로그 행)` — 두 수의 합이 증분이고
    겹쳐 세지 않는다: 들지 못한 카탈로그 행(`CATALOG_`, 상한 · 코드 기준 행에 자리를 내줌)은 확장 표시가 있어도 앞 수에서 뺀다.
    기본 프로파일은 `(0, 0)`."""
    if not extended:
        return 0, 0
    rows = [q for s in all_sequences.values() for q in s if q.get("tc_profile") == TC_PROFILE_EXTENDED]
    displaced = sum(1 for q in rows if str(q.get("strategy") or "").startswith(CATALOG_PREFIX))
    return len(rows) - displaced, displaced


def summarize_reference_code_rows(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """(R85) 정본 규모 문서의 코드 기준 행 — unit 기록의 합(키는 `REFERENCE_CODE_REPORT_KEYS`) + 탐색한 · 행이 생긴 · 오류
    · 설계 입력 없음 · 자리 없음 · 예산 소진 unit 수, 탐색하지 못한 unit 의 사유별 수(`not_searched`, 리뷰 R85 W3)와 탐색 상한."""
    recs = [u.get("reference_code_rows") for u in units if isinstance(u.get("reference_code_rows"), dict)]
    out: Dict[str, Any] = {k: sum(int(r.get(k) or 0) for r in recs) for k in REFERENCE_CODE_REPORT_KEYS}
    skipped = {"searched", "error", "no_room", "no_design_inputs"}
    not_searched: Dict[str, int] = {}
    for r in recs:
        status = str(r.get("status") or "")
        if status not in skipped:
            reason = status.split(":", 1)[0]
            not_searched[reason] = not_searched.get(reason, 0) + 1
    out.update(units=len(recs), searched=sum(1 for r in recs if r.get("status") == "searched"),
               units_with_rows=sum(1 for r in recs if r.get("rows")),
               errors=sum(1 for r in recs if r.get("status") == "error"),
               no_design_inputs=sum(1 for r in recs if r.get("status") == "no_design_inputs"),
               no_room=sum(1 for r in recs if r.get("status") == "no_room"),
               budget_exhausted=sum(1 for r in recs if r.get("budget_exhausted")),
               not_searched=dict(sorted(not_searched.items())), cap_per_search=_SCENARIO_MAX_ROWS)
    return out


def _design_widened(unit: Dict[str, Any], domains: Dict[str, Any], var_types: Dict[str, str]) -> Dict[str, Any]:
    """(R78) Inputs whose design range (설계서 · HSIS 범위 · 값 목록, or a scope domain the design narrowed) is narrower
    than the declared type → the declared type's range — what the searches over values outside the design widen."""
    wide: Dict[str, Any] = {}
    src = unit.get("bounds_source") or {}
    for v, d in domains.items():
        if isinstance(d, tuple) and src.get(v) in ("uds_range", "hsis_range", "uds_values"):
            tb = get_boundary_values(var_types.get(v, ""))
            lo, hi = (tb or {}).get("min"), (tb or {}).get("max")
            if isinstance(lo, int) and isinstance(hi, int) and lo <= d[0] <= d[1] <= hi and (lo, hi) != d:
                wide[v] = (lo, hi)
        elif isinstance(d, dict) and d.get("constraint_source") and not d.get("values") and \
                isinstance(d.get("type_min"), int) and isinstance(d.get("type_max"), int) and \
                (d["type_min"], d["type_max"]) != (d.get("min"), d.get("max")):
            wide[v] = (d["type_min"], d["type_max"])
    return wide


def _append_scenario_fi_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]], ctx: Dict[str, Any]) -> None:
    """(R78) 설계 범위 밖 동작 시나리오 — 설계 범위가 선언 타입보다 좁은 입력이 있고 1차 탐색(`_append_scenario_rows`)이 닿지 못한
    문장 · 분기가 남았으면, 그 입력을 선언 타입 범위로 넓혀 한 번 더 찾는다. 코드는 설계 범위 밖 값을 다룬다(HDPDM01
    `u16s_Direction_Check`: 타이머 설계 0~20, 코드 임계 30 — 정본은 30 으로 ERROR 상태의 복귀 경로를 시험했다;
    `s_PlayProtectChk`: 단계 설계 0~3, 코드의 ACTIVATED 는 4). 넓힌 입력은 설계 범위 값부터 쓰고(`home`), 찾은 벡터의 설계 범위
    밖 값은 목표가 계속 닿는 한 범위 안으로 되돌린다 — 남은 밖 값이 그 목표에 필요한 값이다(리뷰 R78 W1). 그런 행은 설계 범위
    밖 값을 싣는 FI 행(`SCNR_`)이고, 밖 값이 남지 않은 행은 1차 탐색이 놓친 설계 범위 안 시나리오(`SCN_`)다. 1차 탐색이 이미
    닿은 목표(그 행 · 입력이 같은 기존 행 — 상한에 잘린 것은 아님)와 다른 행이 닿는 목표는 찾지 않는다. **모든 확장 행 뒤**(경계 · 강건성 · 출력 관측
    쌍 다음)에 붙는다 — 그 탐색들은 이 행들 없이 돈다(리뷰 R78 C1: 강건성 행의 점을 이 행이 먼저 가져갔다 · W6: 경계 기준 행이
    될 수 있었다). 요약은 `unit["scenario_rows"]` 의 `outside_design_*`."""
    report = unit.get("scenario_rows")
    # (review R80 I-R4-7) a first search without inputs (``no_integer_inputs``) may still have a one-value design input —
    #   the enum search alone, below
    if not isinstance(report, dict) or report.get("error") or report.get("status") not in ("searched", "no_integer_inputs"):
        return
    var_types = ctx["var_types"]
    domains = _scenario_domains(unit, ctx)
    wide = _design_widened(unit, domains, var_types)
    src = unit.get("bounds_source") or {}
    # (R80) a value-set input (enum · state values) over its unit's enumerators: the object can hold a value no
    #   enumerator names — a corrupted or uninitialised state the code's `default:` / last `else` handles (HDPDM01
    #   `s_BuzzerStateCtrl`: the reference reached its default with 0 and 4 around the enumerators 1 ~ 3) — and, when the
    #   design narrows it, the enumerators outside the design. Searched by its own search after the design-range one
    #   (`_append_enum_fi_rows`); such a row is FI like a design-range one (`outside`)
    enum_why: Dict[str, str] = {}
    enum_homes: Dict[str, Tuple[List[int], List[int]]] = {}
    try:
        # (review R80 I-R4-7) a value-set input the design narrows to ONE value has no first-search domain (one value is
        #   no domain) — "always X" is where a value outside it matters most: its home is that value
        singles = _single_value_enum_domains(unit, ctx, domains)
        enum_wide = _outside_enumerator_domains(unit, {**domains, **singles}, var_types, enum_why,
                                                ctx.get("enum_sets"), enum_homes)
    except Exception as exc:  # noqa: BLE001 — (review R80 I-R4-4) the enum search alone is lost, not the design-range one
        _logger.warning("SUTS 열거자 밖 값 준비 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        report["outside_design_enum_error"] = type(exc).__name__
        singles, enum_wide = {}, {}
    report["outside_design_enum_single_value"] = sum(1 for k in singles if k in enum_wide)
    # (review R78 R2 I-R2-6) a design value list (an enum the design restricts, `uds_values`) is not widened — counted
    report.update(outside_design_inputs=len(wide), outside_design_enum_inputs=len(enum_wide),
                  # (review R80 W4 · W-R2-2) value-set inputs not widened: nothing left to widen to (every enumerator in
                  #   the domain, ±1 outside the range) · no declaration gives the type
                  outside_design_enum_at_range_end=sum(1 for w in enum_why.values() if w == "nothing_to_widen"),
                  outside_design_enum_type_unresolved=sum(1 for w in enum_why.values() if w == "type_unresolved"),
                  # (R80) integer design value lists — an enum one is widened above
                  outside_design_value_sets=sum(1 for v, d in domains.items()
                                                if src.get(v) in ("uds_range", "hsis_range", "uds_values")
                                                and var_types.get(v) != _ENUM_TYPE
                                                # (review R80 I-R5-1) an enum element / pointer target the enum
                                                #   search takes is not counted here too
                                                and v not in enum_wide and v not in enum_why
                                                and (isinstance(d, list) or (isinstance(d, dict) and d.get("values")
                                                                             and not d.get("harness_member")))))
    first_ran = report.get("status") == "searched"
    if not (wide or enum_wide) or (first_ran and int(report.get("reached_clean") or 0) >= int(report.get("targets") or 0)):
        return
    if not first_ran:
        wide = {}   # no first search: only the enum search (over its one-value inputs) runs
    outputs = _scenario_outputs(ctx, _search_rows(sequences))

    def existing_rows() -> List[Dict[str, Any]]:
        # the first search's operating vectors first — the climb starts are the first `MAX_STARTS` (review R78 R3
        #   I-R3-1: in document order the first scenario row sat past them)
        return [s.get("inputs") or {} for s in _scenario_rows_first(_search_rows(sequences))]

    def add_rows(found: List[Dict[str, Any]], span: Dict[str, Any], enums: Dict[str, Dict[str, Any]]) -> int:
        """The rows a search found — FI (`SCNR_`) when a value outside its home range stays, else in-range (`SCN_`);
        numbered after the rows already there. The number of FI rows."""
        n_in = sum(1 for s in sequences if str(s.get("strategy") or "").startswith(SCENARIO_PREFIX))
        n_fi = sum(1 for s in sequences if str(s.get("strategy") or "").startswith(SCENARIO_FI_PREFIX))
        fi = 0
        for row in found:
            outside = {k: x for k, x in row["inputs"].items() if k in span and not _at_home(span[k], x)}
            if outside:
                strategy = f"{SCENARIO_FI_PREFIX}{n_fi + fi}"
                fi += 1
            else:
                strategy = f"{SCENARIO_PREFIX}{n_in}"
                n_in += 1
            _scenario_row(sequences, row, strategy, outputs, var_types, outside, span, enums)
        return fi

    if wide:
        # (R78) the declared types over the design ranges — this search is as R79 left it; (R80) the enum search is its
        #   own, after it
        span = {k: (d if isinstance(d, tuple) else (d["min"], d["max"])) for k, d in domains.items() if k in wide}
        existing = existing_rows()
        # (review R79 W3) no fault-exposing targets here — a row found over the widened domains is an FI row by what it
        #   carries; the exposing targets are the first search's
        again = find_scenarios(unit, {**domains, **wide}, outputs, existing,
                               covered=existing, home=span, expose=False)
        rep = again["report"]
        report.update(outside_design_searched=int(rep.get("targets") or 0) - int(rep.get("covered_before") or 0),
                      outside_design_reached=int(rep.get("reached_clean") or 0) - int(rep.get("covered_before") or 0),
                      outside_design_not_reached=int(rep.get("not_reached") or 0)
                      + int(rep.get("reached_unclean_only") or 0),
                      outside_design_runs=int(rep.get("runs") or 0), outside_design_steps=int(rep.get("steps") or 0),
                      outside_design_cut=int(rep.get("cut") or 0),
                      outside_design_duplicates=int(rep.get("duplicates") or 0),
                      outside_design_budget_exhausted=bool(rep.get("budget_exhausted")),
                      outside_design_status=str(rep.get("status") or ""),
                      outside_design_pools_capped=int(rep.get("pools_capped") or 0),
                      outside_design_starts_capped=int(rep.get("starts_capped") or 0))
        n_fi = add_rows(again["rows"], span, {})
        report["outside_design_rows"] = n_fi
        report["outside_design_in_range_rows"] = len(again["rows"]) - n_fi
    if enum_wide:
        _append_enum_fi_rows(unit, sequences, report, domains, wide, enum_wide, outputs, existing_rows, add_rows, src,
                             enum_homes, ctx.get("var_bounds") or {})


# (R80) the enum search's own counters — reset together when it fails (review R80 I-R4-5)
_ENUM_SEARCH_KEYS = ("outside_design_enum_searched", "outside_design_enum_reached", "outside_design_enum_not_reached",
                     "outside_design_enum_rows", "outside_design_enum_in_range_rows", "outside_design_enum_runs",
                     "outside_design_enum_steps", "outside_design_enum_cut", "outside_design_enum_duplicates",
                     "outside_design_enum_pools_capped", "outside_design_enum_starts_capped")


def _append_enum_fi_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]], report: Dict[str, Any],
                         domains: Dict[str, Any], wide: Dict[str, Any], enum_wide: Dict[str, List[int]],
                         outputs: List[str], existing_rows: Callable[[], List[Dict[str, Any]]],
                         add_rows: Callable[..., int], src: Dict[str, Any],
                         homes: Dict[str, Tuple[List[int], List[int]]], var_bounds: Dict[str, Any]) -> None:
    """(R80) 열거자 밖 값 탐색 — 1 · 2차 탐색이 닿지 못한 목표를, 값 목록 입력(enum · 상태값)만 넓힌 값 목록
    (`_outside_enumerator_domains`)으로 넓혀 한 번 더 찾는다(리뷰 R80 I-R4-6: 설계 범위 입력까지 넓히면 2차 탐색이 예산을 다 쓴
    목표를 또 찾고, 설계 범위 밖 값만 실은 행을 이 탐색의 행으로 셌다 — 두 축이 함께 필요한 목표는 찾지 않는다). 자기 예산 ·
    카운터(`outside_design_enum_*`) · 오류(그 행과 카운터만 버림).
    **2차(설계 범위 밖) 탐색 뒤**에 따로 돈다(R80 측정 r80c: enum 값을 2차 탐색에 섞자 그 탐색의 오르기가 다른 데서 끝나 HDPDM01
    `s_IsDoorStop` 이 행 하나와 생성 kill 하나를 잃었다 — 기존 탐색은 그대로 두고 더한다, R78 경계 기준과 같은 규칙). 그 앞까지의
    행이 덮은 목표는 찾지 않는다."""
    start = len(sequences)
    try:
        # (review R80 W-R3-1) an enum's home is the value set the design keeps (or its enumerators) — a design list with a
        #   gap leaves the enumerator in it outside, a value between enumerators is never at home
        span: Dict[str, Any] = {k: list(homes[k][0]) for k in enum_wide}
        existing = existing_rows()
        found = find_scenarios(unit, {**domains, **enum_wide}, outputs, existing,
                               covered=existing, home=span, expose=False)
        rep = found["report"]
        report.update(
            outside_design_enum_searched=int(rep.get("targets") or 0) - int(rep.get("covered_before") or 0),
            outside_design_enum_reached=int(rep.get("reached_clean") or 0) - int(rep.get("covered_before") or 0),
            outside_design_enum_not_reached=int(rep.get("not_reached") or 0) + int(rep.get("reached_unclean_only") or 0),
            outside_design_enum_runs=int(rep.get("runs") or 0), outside_design_enum_steps=int(rep.get("steps") or 0),
            outside_design_enum_cut=int(rep.get("cut") or 0),
            outside_design_enum_duplicates=int(rep.get("duplicates") or 0),
            outside_design_enum_budget_exhausted=bool(rep.get("budget_exhausted")),
            # (review R80 W-R4-2) where the list caps cut — this search
            outside_design_enum_pools_capped=int(rep.get("pools_capped") or 0),
            outside_design_enum_starts_capped=int(rep.get("starts_capped") or 0),
            outside_design_enum_status=str(rep.get("status") or ""))
        # (review R80 W-R3-2) the label says what the value is outside of: the design range (or value list) when the
        #   design gave one and the value leaves it, else the enumerators — "inside the design" said when it is
        info: Dict[str, Dict[str, Any]] = {}
        for k in enum_wide:
            b = var_bounds.get(k) or {}
            design: Any = None
            if src.get(k) in ("uds_range", "hsis_range") and isinstance(b.get("min"), int) and isinstance(b.get("max"), int):
                design = (b["min"], b["max"])
            elif src.get(k) == "uds_values":
                design = list(homes[k][0])
            info[k] = {"design": design, "enumerators": (homes[k][1][0], homes[k][1][-1])}
        fi = add_rows(found["rows"], span, info)
        report["outside_design_enum_rows"] = fi
        report["outside_design_enum_in_range_rows"] = len(found["rows"]) - fi
    except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document or the other searches' rows
        _logger.warning("SUTS 열거자 밖 동작 시나리오 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        del sequences[start:]
        # (review R80 I-R4-5) nothing of the dropped search stays — counters, budget, caps
        for k in _ENUM_SEARCH_KEYS:
            report[k] = 0
        report["outside_design_enum_budget_exhausted"] = False
        report["outside_design_enum_status"] = ""
        report["outside_design_enum_error"] = type(exc).__name__


def _single_value_enum_domains(unit: Dict[str, Any], ctx: Dict[str, Any], domains: Dict[str, Any]
                               ) -> Dict[str, List[int]]:
    """(review R80 I-R4-7) Value-set inputs (enum type) without a search domain because the design keeps one value —
    `_boundary_domains` reads a one-value list as no domain. The same design filter: the design range's enumerators, or
    the design value list's."""
    var_types, var_bounds = ctx.get("var_types") or {}, ctx.get("var_bounds") or {}
    sets = ctx.get("enum_sets") if ctx.get("enum_sets") is not None else (unit.get("value_domains") or {})
    src = unit.get("bounds_source") or {}
    out: Dict[str, List[int]] = {}
    for v in ctx.get("input_vars") or []:
        if v in domains or var_types.get(v) != _ENUM_TYPE or v in set(ctx.get("unknown") or ()):
            continue
        try:
            vals = sorted({int(x) for x in ((sets.get(v) or {}).get("values") or [])})
        except (TypeError, ValueError, AttributeError):
            continue
        b = var_bounds.get(v) or {}
        if src.get(v) in ("uds_range", "hsis_range") and isinstance(b.get("min"), int) and isinstance(b.get("max"), int):
            vals = [x for x in vals if b["min"] <= x <= b["max"]]
        elif src.get(v) == "uds_values":
            design = set(((unit.get("uds_param_info") or {}).get(v) or {}).get("values") or [])
            vals = [x for x in vals if x in design]
        if len(vals) == 1:
            out[v] = vals
    return out


def _outside_label(info: Dict[str, Any], x: int) -> str:
    """(R80 review W-R3-2) What a value-set input's FI value is outside of: the design range or value list when the
    design gave one and the value leaves it; else the enumerators (with "inside the design" when it is)."""
    a, b = info["enumerators"]
    design = info.get("design")
    if isinstance(design, tuple):
        if not design[0] <= x <= design[1]:
            return f"설계 {design[0]}~{design[1]} 밖"
        return f"열거자 {a}~{b} 밖 · 설계 {design[0]}~{design[1]} 안"
    if isinstance(design, list):
        return "설계 값 " + ", ".join(str(v) for v in design) + " 밖"
    return f"열거자 {a}~{b} 밖"


def _outside_enumerator_domains(unit: Dict[str, Any], domains: Dict[str, Any], var_types: Dict[str, str],
                                why: Optional[Dict[str, str]] = None, enum_sets: Optional[Dict[str, Any]] = None,
                                homes: Optional[Dict[str, Tuple[List[int], List[int]]]] = None) -> Dict[str, List[int]]:
    """(R80) 열거자 밖 값 탐색(`_append_enum_fi_rows`)이 넓힐 값 목록 입력 → 넓힌 값 목록: 그 번역 단위의 모든 열거자(`value_domains` — 설계서 범위 · 값 목록이
    좁힌 입력이면 설계 밖 열거자도, 설계 밖 값이라 FI) ∪ 열거자 범위 ±1(선언 타입 · enum 입력 범위 안). 넓힐 값이 없으면 넣지
    않는다. (R80 측정) HDPDM01 `s_BuzzerState` 는 SwUDS 범위 0x01~0x03 을 받아(`uds_range`) 설계가 좁힌 목록으로 빠졌다 — enum 의
    설계 범위는 FI 가 무엇인지 바꾸지 않는다. 정수 입력의 설계 값 목록은 넓히지 않고 센다(R78 I-R2-6, `outside_design_value_sets`)."""
    out: Dict[str, List[int]] = {}
    sets = enum_sets if enum_sets is not None else (unit.get("value_domains") or {})
    types: Dict[str, Dict[str, Any]] = {}
    for v, d in domains.items():
        try:
            if isinstance(d, dict) and d.get("values"):
                # (review R80 I-R3-2) an element's / a pointer target's / a stub return's enum domain (`_scope_domain`):
                #   the values inside its min ~ max are home; (I-R4-2) every enumerator comes from the enum type (a design
                #   range has already overwritten ``values``); (I-R4-3) an integer value list is no enum — counted, as R78
                ctype = d.get("ctype")
                if not (isinstance(ctype, dict) and ctype.get("enum")):
                    continue
                lo_d, hi_d = int(d.get("min")), int(d.get("max"))
                home = sorted({int(x) for x in d["values"] if lo_d <= int(x) <= hi_d})
                every = _enumerator_values(unit, ctype) or [int(x) for x in d["values"]]
                types[v] = ctype
            elif var_types.get(v) == _ENUM_TYPE and isinstance(d, list) and d:
                home = sorted({int(x) for x in d})
                # (review R80 I-R3-3) the generation's value sets (pointer targets too), else the unit's value domains
                every = [int(x) for x in (((sets.get(v) or (unit.get("value_domains") or {}).get(v)) or {})
                                          .get("values") or [])]
            else:
                continue
        except (TypeError, ValueError):
            continue
        if not home:
            continue
        full = sorted(set(every) | set(home))
        widened, reason = _value_set_widening(unit, v, full, types.get(v))
        widened = widened or full
        if widened != home:
            out[v] = widened
            if homes is not None:
                homes[v] = (home, full)
        elif why is not None:
            # (review R80 W-R2-2 · I-R3-1) not widened — no declaration gives a usable type, or nothing is left
            why[v] = reason or "nothing_to_widen"
    return out


def _parameter_ctype(unit: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """(review R80 W-R2-2) The resolved type of the function's parameter ``name`` (its declaration), or None."""
    from generators import c_project_context as _cpc
    from generators.c_source_oracle import Unsupported, _parsed_function
    from generators.mcdc_design import _function_name, _scope_type, _text
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    parser = _cpc.shared_parser()
    if not scope or parser is None or not unit.get("source_text"):
        return None
    raw = str(unit["source_text"]).encode()
    try:
        _root, fn, _shared = _parsed_function(parser, raw, str(unit.get("name") or ""), scope)
        _, fdecl = _function_name(fn, raw)
    except (Unsupported, AttributeError, TypeError, ValueError):
        return None
    params = fdecl.child_by_field_name("parameters") if fdecl is not None else None
    for p in params.named_children if params is not None else []:
        ident, typ = p.child_by_field_name("declarator"), p.child_by_field_name("type")
        if p.type != "parameter_declaration" or ident is None or ident.type != "identifier" or typ is None:
            continue
        if _cpc._declared_name(ident, raw) == name:
            try:
                return _scope_type(scope, _text(typ, raw))
            except _cpc.Unresolved:
                return None
    return None


def _value_set_ctype(unit: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """(R80) The declared type of a value-set input — the unit's global, 1-D element, pointer-parameter target or
    (review R80 W-R2-2) parameter; None when none declares it."""
    from generators.mcdc_design import _pointee_input
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    base, _, rest = str(name).partition("[")
    # (review R80 I-R3-6) the function's parameter first — a global of the same name is hidden in the body
    t = _parameter_ctype(unit, name) if not rest else None
    if not isinstance(t, dict):
        rec = ((scope.get("arrays") if rest else scope.get("globals")) or {}).get(base)
        t = rec.get("type") if isinstance(rec, dict) else None
    if not isinstance(t, dict) and scope:
        found = _pointee_input(scope, str(unit.get("name") or ""), name)
        t = found[0] if found else None
    return t if isinstance(t, dict) else None


def _enum_outside_values(unit: Dict[str, Any], name: str, values: List[int]) -> List[int]:
    return _value_set_widening(unit, name, values)[0]


def _enumerator_values(unit: Dict[str, Any], ctype: Dict[str, Any]) -> List[int]:
    """(review R80 I-R4-2) Every enumerator of an enum type — the translation unit's declaration (as `_scope_domain`)."""
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    enum = (scope.get("enum_types") or {}).get(ctype.get("enum")) or {}
    # the constants table is lazy — its len is 0 until read, so ``or {}`` would drop it
    consts = scope.get("constants")
    if consts is None:
        return []
    try:
        return sorted({int(consts[m["name"]]["value"]) for m in enum.get("members") or [] if m.get("name") in consts})
    except (TypeError, ValueError, KeyError):
        return []


def _value_set_widening(unit: Dict[str, Any], name: str, values: List[int],
                        ctype: Optional[Dict[str, Any]] = None) -> Tuple[List[int], str]:
    """(R80) 값 목록 ``values``(열거자 · `#define` 상태값)와 그 범위 ±1(선언 타입 범위 안 — C enum 이면 enum 입력이 가질 수
    있는 0 ~ 127 과 멤버 값을 잇는 구간 안, oracle 의 입력 판정과 같은 `enum_input_range` — R90) — 넓힐 값이 없으면 빈 목록. 타입은 선언(전역 · 1차원 원소 ·
    포인터 매개변수 대상 · 매개변수 — `_value_set_ctype`)에서 — 모르면 넓히지 않는다."""
    from generators import c_project_context as _cpc
    # (review R80 I-R4-1) a domain that carries its type (a stub return, an element) is read by it
    t = ctype if isinstance(ctype, dict) else _value_set_ctype(unit, name)
    if t is None or _cpc.is_float(t):
        return [], "type_unresolved"
    try:
        lo, hi = _cpc.type_range(t)
    except (_cpc.Unresolved, KeyError, TypeError, ValueError):
        return [], "type_unresolved"
    if t.get("enum"):
        # (review R80 W4) and inside what an enum input can be — the oracle refuses the rest (`enum_input_range`: 0..127
        #   and the members — R90 review W4); a value set over an integer type (`#define` states — review R80 W-R2-2) has
        #   its type's range
        from generators.c_source_oracle import enum_input_range
        elo, ehi = enum_input_range(unit.get("project_scope"), t)
        lo, hi = max(lo, elo), min(hi, ehi)
    extra = [x for x in (values[0] - 1, values[-1] + 1) if isinstance(lo, int) and isinstance(hi, int) and lo <= x <= hi]
    return (sorted(set(values) | set(extra)), "") if extra else ([], "nothing_to_widen")


def _append_robustness_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]], input_vars: List[str],
                            output_vars: List[str], var_types: Dict[str, str], var_bounds: Dict[str, Dict[str, Any]],
                            unknown_vars: set, declared: Optional[set] = None) -> None:
    """(R31, 확장 프로파일) 타입 폭이 **선언으로 확정된** 입력마다(``declared`` — 이름 패턴·기본값으로 추측한 타입, 타깃마다
    폭이 다른 선언, 포인터는 타입 폭이 지어낸 값이라 뺀다 — R19 채움과 같은 규칙): 설계 범위 [lo, hi] 밖이고 선언 타입 안인
    **직접 비교 상수** K 의 K−1·K·K+1 중 설계 범위 밖·타입 안인 점에 FI 행을 더한다. 기준 행은 후보(`_base_rank` 순, FI 가 아니고 설계 범위가 정해진 입력이 전부 그 범위 안인
    정수 행, 최대 `MAX_ROBUST_BASES`) 중 K−2~K+1 에서 원본 코드를 돌려 도출 출력이 한 기울기로 움직이지 않는 첫 행 — 비교가
    **살아 있는** 행이다(포화 가드는 `x+1` 이 K 에서 멈춘다; KJPDS02_PV `s_LinFailCheckTimer` 의 BV_MID 는 LIN 이상 플래그가
    0 이라 가드에 가지 않았다). 살아 있는 행을 못 찾으면(`not_live`) 첫 후보에 두고 행 설명에 그렇게 적는다 — 유효한 상태에서
    값 하나만 범위 밖으로 넣는 FI 행으로는 여전히 성립하고, 살아 있음은 기준을 고르는 기준이지 행을 빼는 기준이 아니다.
    후보가 없으면 행을 만들지 않고(`no_base`), 점이 셋 미만이라 살아 있음을 볼 수 없으면(`unprobed`) 첫 후보에 둔다.
    살아 있는 비교의 점이 먼저 자리를 받는다(상한에 잘리는 것은 살아 있지 않은 쪽부터). 살아 있는 점만으로 상한이 차면 남은
    상수는 탐침하지 않고 그 점을 잘린 점으로 센다(리뷰 2라운드 I4 — 평가 비용). 같은 입력의 행이 이미 있으면 더하지 않는다.
    살아 있지 않은 기준 행 위의 점은 oracle 이 출력 하나라도 도출할 때만 행이 된다(`underived` — 리뷰 2라운드 W1: 기대값 칸이
    전부 "[검증 필요]" 인 FI 행에 "oracle 도출" 이라 적었다; 살아 있는 점은 그 판정이 이미 전 점의 도출을 요구한다).
    본문을 확정하지 못한 매크로의 인자 안에서만 나온 비교(이 빌드에 없을 수 있다)는 **살아 있는 기준 행이 있을 때만**
    쓴다(`macro_argument_live` / `macro_argument_unconfirmed` — 리뷰 3·4라운드 W-1; 본문을 아는 매크로는
    `compared_constants` 가 본문으로 판정). 요약은 `unit["robustness_rows"]`(키는 `ROBUSTNESS_REPORT_KEYS`)."""
    from generators.boundary_rows import _as_int, compared_constants, comparison_is_live, derives_any
    src = unit.get("bounds_source") or {}
    declared = set(declared or ())
    # (R65) 설계서 값 목록(`uds_values`)도 설계 범위다 — 목록의 최소 ~ 최대 밖 상수가 강건성 점이다
    ranged = [v for v in input_vars
              if src.get(v) in ("uds_range", "hsis_range", "uds_values") and v not in unknown_vars
              and var_types.get(v) != "float"
              and isinstance((var_bounds.get(v) or {}).get("min"), int)
              and isinstance((var_bounds.get(v) or {}).get("max"), int)]
    designed = [v for v in ranged if v in declared]
    report = dict.fromkeys(ROBUSTNESS_REPORT_KEYS, 0)
    report.update(inputs_with_design_range=len(designed), inputs_type_unconfirmed=len(ranged) - len(designed))
    unit["robustness_rows"] = report
    if not designed or not sequences:
        return
    stats: Dict[str, int] = {}
    compared = compared_constants(unit, designed, stats)
    for key in ("undecided_preprocessor_blocks", "inputs_shadowed", "body_unread"):
        report[key] = int(stats.get(key) or 0)
    macro_only = stats.get("macro_argument_constants") or {}
    seen = {json.dumps(s.get("inputs") or {}, sort_keys=True, default=str) for s in _search_rows(sequences)}
    outputs = list(dict.fromkeys([*output_vars, *(k for s in _search_rows(sequences) for k in (s.get("expected") or {}))]))
    bases: List[tuple] = []
    # (R78) 동작 시나리오 행은 기존 후보(`MAX_ROBUST_BASES`) **뒤에 더한** 후보다 — 기존 후보 중 비교가 살아 있는 행이 있으면 그
    #   행이 그대로 기준이고, 없을 때만 시나리오 행이 기준이 된다(옮기지 않고 더한다)
    limits = {False: MAX_ROBUST_BASES, True: MAX_ROBUST_SCENARIO_BASES}
    taken = {False: 0, True: 0}
    for s in _base_order(_search_rows(sequences)):
        scenario = _is_scenario(s)
        if taken[scenario] >= limits[scenario]:
            continue
        if resolve_seq_test_method(s.get("strategy")) == _METHOD_FI:
            continue                        # a base holds valid values only (the FI rows carry out-of-range ones)
        ints = {k: _as_int(x) for k, x in (s.get("inputs") or {}).items()}
        if not ints or any(x is None for x in ints.values()) or any(e[0] == ints for e in bases):
            continue
        if any(u in ints and not var_bounds[u]["min"] <= ints[u] <= var_bounds[u]["max"] for u in ranged):
            continue                        # (review I3) a REQ row may carry a case value outside the design range
        bases.append((ints, s))
        taken[scenario] += 1
    live_points: List[tuple] = []
    other_points: List[tuple] = []
    live_keys: set = set()

    def row_key(base_inputs: Dict[str, Any], v: str, p: int) -> str:
        return json.dumps({**base_inputs, v: _format_test_value(p, var_types.get(v, "uint8_t"))}, sort_keys=True,
                          default=str)

    for v in designed:
        dlo, dhi = var_bounds[v]["min"], var_bounds[v]["max"]
        tb = get_boundary_values(var_types.get(v, ""))
        tlo, thi = (tb or {}).get("min"), (tb or {}).get("max")
        if not isinstance(tlo, int) or not isinstance(thi, int):
            report["inputs_no_type_width"] += 1         # (review round 2 I5) e.g. an enum with a design range
            continue
        for k in sorted(set(compared.get(v, ())) | set(macro_only.get(v, ()))):
            in_macro = k not in compared.get(v, ())
            if dlo <= k <= dhi:
                continue
            if not tlo <= k <= thi:
                report["constants_outside_type"] += 1
                continue
            report["compared_constants_outside_design"] += 1
            if not bases:
                report["no_base"] += 1
                continue
            points = [(p, in_macro) for p in (k - 1, k, k + 1) if tlo <= p <= thi and not dlo <= p <= dhi]
            if len(live_keys) >= MAX_ROBUST_ROWS:
                report["cut"] += len(points)            # the cap is full of rows whose comparison is live
                continue
            probe = [p for p in (k - 2, k - 1, k, k + 1) if tlo <= p <= thi]
            if len(probe) < 3:
                chosen, live = bases[0], None
            else:
                chosen = next((b for b in bases if comparison_is_live(unit, b[0], v, probe, outputs)), None)
                live = chosen is not None
            if in_macro and not live:
                report["macro_argument_unconfirmed"] += 1   # the comparison may not exist in this build
                continue
            if live:
                report["live"] += 1
                report["macro_argument_live"] += int(in_macro)
            elif live is None:
                report["unprobed"] += 1
            elif not live:
                report["not_live"] += 1
                chosen = bases[0]
            if live:
                live_points += [(v, k, p, chosen, live, m) for p, m in points]
                live_keys.update(key for key in (row_key(chosen[1].get("inputs") or {}, v, p) for p, _m in points)
                                 if key not in seen)
            else:
                other_points += [(v, k, p, chosen, live, m) for p, m in points]
    for v, k, p, (base_ints, base), live, in_macro in live_points + other_points:
        inputs = {**(base.get("inputs") or {}), v: _format_test_value(p, var_types.get(v, "uint8_t"))}
        key = json.dumps(inputs, sort_keys=True, default=str)
        if key in seen:
            report["duplicates"] += 1
            continue
        if report["rows"] >= MAX_ROBUST_ROWS:
            report["cut"] += 1
            continue
        if not live and not derives_any(unit, {**base_ints, v: p}, outputs):
            report["underived"] += 1
            continue
        seen.add(key)
        dlo, dhi = var_bounds[v]["min"], var_bounds[v]["max"]
        reach = (" — 본문을 확정하지 못한 매크로의 인자 안 비교, 이 기준 행에서 원본 코드의 출력이 그 점들에서 꺾이는 것을 "
                 "봤다(다른 원인일 수도 있다)" if in_macro else
                 "" if live else
                 " — 이 기준 행에서 그 비교에 닿는지 확인하지 못했다(비교가 살아 있는 기준 행을 못 찾음)" if live is False else
                 " — 점이 셋 미만이라 이 기준 행이 그 비교에 닿는지 보지 않았다")
        sequences.append({
            "seq_num": len(sequences) + 1, "inputs": inputs,
            "expected": {o: f"{VERIFY_PREFIX} robustness" for o in outputs},
            "strategy": f"{ROBUST_PREFIX}{report['rows']}", "tc_profile": TC_PROFILE_EXTENDED,
            "description": (f"설계 범위 밖 강건성: {v}={p} — 소스에 {v} 와 상수 {k} 의 직접 비교가 있다(설계 범위 {dlo}~{dhi} 밖 · "
                            f"선언 타입 안, 기준 행 {base.get('strategy')}{reach}). 기대값은 소스 oracle 이 도출한 출력만 "
                            "확정(코드 일관성 · 미실행)"),
            "robustness": {"variable": v, "constant": k, "value": p, "design_range": [dlo, dhi], "live": live,
                           "in_macro_argument": in_macro},
        })
        report["rows"] += 1


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
    seen = {json.dumps(s.get("inputs") or {}, sort_keys=True, default=str) for s in _search_rows(sequences)}
    rows = [s for s in sequences if _catalog_name(s.get("strategy")).startswith("MCDC_")]
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
        if strategy.startswith(CODE_PREFIX):
            kept.append(seq)   # (R85) a reference-scale code row — kept, and not the earlier row of an extended one
            continue
        if key in seen:
            # (리뷰 R85 I-2) 정본 규모 문서에 들지 못한 카탈로그 행(`CATALOG_`)은 빼지 않는다 — R85 전엔 그 행이 정본 규모
            #   행이라 빠진 적이 없고, CATALOG_BV_MID 는 첫 기준 행이다(확장에서 남긴 중복으로 센다)
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


def summarize_reference_columns(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """(R86) 정본 규모 문서의 열 — 확장 생성이 정한 열을 쓴 unit · 더한 입력 · 출력 열 수 · 확장 생성이 실패해 설계서 열로 만든 unit."""
    recs = [u.get("reference_columns") for u in units if isinstance(u.get("reference_columns"), dict)]
    return {"units": len(recs), "units_with_added_inputs": sum(1 for r in recs if r.get("inputs_added")),
            "units_with_added_outputs": sum(1 for r in recs if r.get("outputs_added")),
            "inputs_added": sum(int(r.get("inputs_added") or 0) for r in recs),
            "outputs_added": sum(int(r.get("outputs_added") or 0) for r in recs),
            "errors": dict(Counter(str(r["error"]) for r in recs if r.get("error"))),
            # (review R86 I2) the extended generation fell back to the design columns inside — the columns it kept
            "units_extension_errors": sum(1 for r in recs if r.get("extension_errors")),
            # (review R86 W-R3-2 · W-R4-1) three kinds — the input completion failed (both records carry the error and
            #   the columns went back to the design's); only the written-output axis stopped in a round (the input
            #   columns and the earlier rounds' outputs stay); only the final step failed (its late outputs went back)
            "units_extension_round_errors": sum(1 for r in recs if "source_read_inputs" in (r.get("extension_errors") or {})),
            "units_extension_output_errors": sum(1 for r in recs if "source_written_outputs" in (r.get("extension_errors") or {})
                                                 and "source_read_inputs" not in (r.get("extension_errors") or {})),
            # (review R86 I-R5-1) only when it is the sole error — a unit that also failed earlier is said there once
            "units_extension_final_errors": sum(1 for r in recs if set(r.get("extension_errors") or {})
                                                == {"source_written_outputs.final"}),
            # (review R86 W2) the reference-scale rows differ from the extended document's block — R75 inclusion broken
            "units_block_mismatch": sum(1 for r in recs if r.get("block_mismatch")),
            "block_mismatch": dict(Counter(str(r["block_mismatch"]) for r in recs if r.get("block_mismatch")))}


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


def _catalog_name(strategy: Any) -> str:
    """(R85) 전략 이름 — 정본 규모 문서에서 자리를 내준 카탈로그 행(`CATALOG_BV_MIN`)은 원래 이름(`BV_MIN`)으로 판정한다."""
    s = str(strategy or "").strip()
    return s[len(CATALOG_PREFIX):] if s.startswith(CATALOG_PREFIX) else s


def resolve_seq_test_method(strategy: Any) -> str:
    """시퀀스 하나의 Test Method — 정본은 **시퀀스 그룹 단위**로 REQ/FI 를 나눈다. (R31) 설계 범위 밖 강건성 행도 FI."""
    s = _catalog_name(strategy)
    return _METHOD_FI if s in _FI_STRATEGIES or s.startswith((ROBUST_PREFIX, SCENARIO_FI_PREFIX, PROPAGATE_FI_PREFIX)) \
        else _METHOD_REQ


def resolve_seq_gen_method(strategy: Any) -> str:
    """시퀀스 하나의 TC Generation Method — 경계값이면 `AOR/ABV`, 조건 조합이면 `AOR/AEC`. (R85) 코드 기준 행은 동작 시나리오
    행과 같은 등가 분할(코드가 나누는 구간 · 분기 결과)이다."""
    s = _catalog_name(strategy)
    if s.startswith("COND_COMB_") or s.startswith("SWITCH_") or s.startswith("MCDC") or s.startswith(MCDC_FILL_PREFIX) \
            or s.startswith(OBS_MCDC_PREFIX) or s.startswith(SCENARIO_PREFIX) or s.startswith(STUB_APART_PREFIX) \
            or s.startswith(PROPAGATE_PREFIX) or s.startswith(PROPAGATE_FI_PREFIX) or s.startswith(CODE_PREFIX):
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
    reference_cap: Optional[int] = _DEFAULT_SEQ_COUNT,
) -> List[Dict[str, Any]]:
    """Generate test sequences for a unit function.

    (R85) 정본 규모 블록의 행 수 — 기본 프로파일은 `max_seq`(None 이면 카탈로그 전부), 확장은 `reference_cap`(같은 SCM 의 정본
    규모 문서가 쓴 상한 — `generate_suts` 의 `max_sequences`; None 이면 카탈로그 전부): 두 문서가 같은 블록을 가져야 확장 문서의
    앞부분이 정본 규모 문서다(리뷰 R85 C1).

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
    # (R40) 포인터 매개변수가 가리키는 대상 입력(`p[0]` · `p[0].a`)의 **소스 선언** 타입 — 행이 이미 싣고 있다
    #   (R19 소스 읽기 분류와 섞지 않는다 — 카탈로그 구조를 정하는 `_r19_typed` 밖)
    _pointee_keys, _pointee_domains = pointee_input_types(unit, list(input_vars))
    _pointee_types = {k: v for k, v in _pointee_keys.items()
                      if _normalize_type(str(_base_cache.get(k) or "")) in ("", _UNKNOWN_TYPE)}
    type_cache = {**_base_cache, **_src_types, **_pointee_types, **_ptypes} \
        if (_ptypes or _src_types or _pointee_types) else _base_cache
    # (R73 N92) enum 값 집합이 있는 변수는 타입 `enum` — 경계값은 열거자의 최소/가운데/최대, 범위 밖은 ±1.
    #   (R40 리뷰 W5) 포인터 대상의 열거자 값 집합은 다른 출처가 없을 때만
    _domains = {**_pointee_domains, **(unit.get("value_domains") or {})} if _pointee_domains \
        else (unit.get("value_domains") or {})
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
            if range_bounds((_uds_info.get(v) or {}).get("range")) or range_bounds(_hsis_rng.get(v)) \
                    or _uds_value_bounds(_uds_info.get(v)):
                return _RANGE_TYPE
        return t

    _range_conflicts: List[str] = []
    _renamed_pointees = set((((unit.get("pointer_parameters") or {}).get("renamed")) or {}).values())
    # (R65) 설계서가 적었지만 읽지 못한 Value Range — 변수 → 사유(`read_value_range`). 값은 다음 출처로 간다.
    _uds_unread: Dict[str, str] = {}
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
            # (R81) a parameter renamed to its pointee (`p` → `p[0]`) carries the design's row of the pointer itself
            _bucket = _pointer_ranges if _is_pointer_decl(v) or v in _renamed_pointees else _range_conflicts
            if _msg not in _bucket:
                _bucket.append(_msg)
            return False
        return True

    def _bounds_of(v: str, t: str) -> Dict[str, Any]:
        rb = range_bounds((_uds_info.get(v) or {}).get("range"))
        if rb and _fits_type(rb, t, v, "SwUDS"):
            _bsrc[v] = "uds_range"
            # (R65) 설계 범위가 선언 타입의 전폭과 같으면 설계가 타입 밖의 정보를 주지 않는다 — 타입 표의 경계값을 그대로
            #   쓴다(가운데 값: 타입 표 0 · `(lo+hi)//2` 는 -1). HDPDM01 이 부호 전폭을 `0x7FFF ~ 0x8000` 으로 적은 323 행이
            #   R65 에서 범위로 읽히며 가운데 값만 0 → -1 로 바뀌어 기준 행 · 경계 탐색이 흔들렸다(변이 판별이 준 함수 3)
            tb = _TYPE_BOUNDARIES.get(t) if t in _TYPE_BOUNDARIES and t != "float" else None
            if tb and (rb["min"], rb["max"]) == (tb["min"], tb["max"]):
                return dict(tb)
            return rb
        # (R65) 설계서가 적은 값 목록(`0, 5, 15`) — 범위 다음, 열거자보다 먼저(이 변수에 대해 더 구체적으로 말한 문서다)
        vb = _uds_value_bounds(_uds_info.get(v))
        if vb and t == _ENUM_TYPE:
            # 열거형 변수의 설계 값 목록은 열거자여야 한다 — 아니면 두 문서가 어긋난 것이라 열거자로 내려가고 센다(MC/DC
            #   `_apply_design_range` 와 같은 판정 — 리뷰 R65 2차 N4)
            _enums = set((enum_bounds(_domains.get(v)) and (_domains.get(v) or {}).get("values")) or [])
            _vals = list(((_uds_info.get(v) or {}).get("values")) or [])
            if _enums and not set(_vals) <= set(int(x) for x in _enums):
                _msg = f"{v}(SwUDS 값 목록 {','.join(str(x) for x in _vals)} ⊄ 열거자)"
                _raw_text = str((_uds_info.get(v) or {}).get("range_text") or "")
                if _raw_text:
                    _msg += f" ← 원문 `{_raw_text}`"
                if _msg not in _range_conflicts:
                    _range_conflicts.append(_msg)
                vb = {}
        if vb and _fits_type(vb, t, v, "SwUDS"):
            _bsrc[v] = "uds_values"
            return vb
        _unread = (_uds_info.get(v) or {}).get("range_unread")
        if _unread and v not in _uds_unread:
            # 설계서가 무언가 적었지만 읽지 못한 칸 — 값은 아래 출처(타입 폭 등)로 가고 사유는 센다(공시 `suts_uds_reading`)
            _uds_unread[v] = str(_unread)
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
        unit["uds_range_unread"] = _uds_unread
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
        # (R80) 입출력 없는 unit 도 실행이 쓴 객체를 받는다 — 출력 목록 밖 쓰기 소견(기대 열 보완은 하지 않는다)
        return apply_sequence_evidence(unit, seqs[:max_seq], written=True)

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
    unit["uds_range_unread"] = _uds_unread

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
    # (R80 review C1) and the design output list — outputs the source writes (R80) are columns, not structure: a design
    #   with no outputs keeps its VOID_SIDE_EFFECT row and the BV_*_INV labels' clamp/guard reading
    _design_out_list = ([v for v in unit["design_output_vars"] if v in output_vars]
                        if isinstance(unit.get("design_output_vars"), list) else list(output_vars))
    _added_inputs = [v for v in input_vars if v not in set(_design_inputs)]
    _added_set_all = frozenset(_added_inputs)
    # (R82) inputs added only as a write's prior value — the function writes them, it does not read them
    _prior_inputs = _prior_input_names(unit)
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
    if _design_inputs and not _design_out_list and indirect_vars:
        strategies.append(("VOID_SIDE_EFFECT", "_void_se"))

    # GAP 6: MC/DC — 결정식을 **실제로 평가해** 찾은 unique-cause 독립 영향 쌍의 입력 벡터(`generators.mcdc_design`).
    # ⚠ 예전 경로(regex `_extract_mcdc_conditions`)는 "전부 참 + 하나만 거짓(나머지 중간값)" 을 만들어 OR 식에서
    #   독립 영향이 0 이었다(`a>10 || b>20` 에서 a 를 뒤집어도 b 가 참이라 결과가 안 바뀐다) — 기법 주장만 있고 쌍이 없었다.
    #   도메인은 **선언**에서 온 것만 쓴다(이름 패턴 추측 금지). 못 푸는 결정은 쌍 없이 사유를 남기고 분모에 남는다.
    # (R19) 설계 입력 목록 위에서 — 기본 자리(`_BASE_MCDC_SLOTS`)의 벡터가 정본 규모 문서와 같다.
    # (R58) 확장 프로파일은 그 설계가 쌍을 하나도 못 만든 결정만 소스가 읽어 더한 입력까지 써서 다시 설계하고
    #   (`_mcdc_source_read_pass`), 새 벡터는 기본 설계 벡터 **뒤** 확장 자리에만 붙인다 — 기본 자리 · 기본 설계 결정은 그대로.
    _mcdc_unit = dict(unit, input_vars=list(_design_inputs)) if _added_inputs else unit
    _mcdc_report = build_mcdc_design(_mcdc_unit, declared_domains=_mcdc_declared_domains(
        _design_inputs, _type_of, _domains, _declared, _is_pointer_decl, set(_ptypes)))
    unit["mcdc_design"] = _mcdc_report
    _mcdc_vectors: List[Dict[str, int]] = list(_mcdc_report.get("selected_inputs") or [])
    # (R72 리뷰 W2) 조건이 많아 조건마다 짝지은 결정의 벡터(설계가 맨 뒤에 둔 `wide_vector_count` 개)는 기본 자리(7)가 남을
    #   때만 기본 자리에 들고, 나머지는 확장 자리의 맨 뒤(2차 설계 벡터 뒤)로 간다 — 2차 설계 행(`MCDC_7`~)의 이름이 R72 전과 같다
    _wide_n = min(int(_mcdc_report.get("wide_vector_count") or 0), len(_mcdc_vectors))
    _mcdc_wide = _mcdc_vectors[len(_mcdc_vectors) - _wide_n:]
    _mcdc_vectors = _mcdc_vectors[:len(_mcdc_vectors) - _wide_n]
    _wide_room = max(0, _BASE_MCDC_SLOTS - len(_mcdc_vectors))
    _mcdc_vectors.extend(_mcdc_wide[:_wide_room])
    _mcdc_late_wide = _mcdc_wide[_wide_room:]
    _mcdc_roles = _mcdc_vector_roles(_mcdc_report)
    _mcdc_base_n = len(_mcdc_vectors)
    for mc_idx in range(min(_mcdc_base_n, _BASE_MCDC_SLOTS)):
        strategies.append((f"MCDC_{mc_idx}", f"_mcdc_{mc_idx}"))
    _mcdc_ext: Optional[Dict[str, Any]] = None
    if extended and _added_inputs:
        try:
            # (리뷰 R58 3차 I-1) 도메인은 패스 안에서, 기록을 만든 뒤에 구한다 — 여기서 실패하면 무엇을 다시 탐색하려 했는지가 사라졌다
            _mcdc_ext = _mcdc_source_read_pass(unit, _mcdc_report, lambda: _mcdc_declared_domains(
                list(input_vars), _type_of, _domains, _declared, _is_pointer_decl, set(_ptypes)), _added_inputs)
        except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
            _logger.warning("SUTS MC/DC 2차 설계(소스가 읽는 입력) 실패(%s): %s", unit.get("name"), exc, exc_info=True)
            # (리뷰 R58 W2) 무엇을 다시 설계하려 했는지(`decisions_searched`)는 남기고 실패를 더한다 — 통째로 바꾸면 공시가 말을 잃는다
            _mcdc_report["source_read_pass"] = {**(_mcdc_report.get("source_read_pass") or {}), "error": type(exc).__name__}
            _mcdc_ext = None
        if _mcdc_ext:
            # (리뷰 R58 W1) 기본 자리 이름(`MCDC_0`~`MCDC_6`)은 기본 설계 몫 — 기본 벡터가 자리보다 적어도 2차 벡터는 `MCDC_7`
            #   부터다(R75 이름 규칙 `is_extended_strategy`: 이름만 보고 확장 행을 가른다). 빈 자리는 행을 만들지 않는다.
            _mcdc_vectors.extend([{}] * max(0, _BASE_MCDC_SLOTS - _mcdc_base_n))
            _mcdc_vectors.extend(_mcdc_ext["vectors"])
    # (R72 리뷰 C1) 2차 설계 행은 `_mcdc_base_n` 부터 이 번호 앞까지 — 그 뒤는 기본 설계의 남은 넓은 벡터다(finalize 를 기본
    #   설계로 하고 라벨에 2차 설계 출처를 붙이지 않는다)
    _mcdc_late_start = len(_mcdc_vectors)

    def _mcdc_second(seq: Dict[str, Any]) -> bool:
        return _mcdc_base_n <= _mcdc_slot(seq) < _mcdc_late_start
    if _mcdc_ext or _mcdc_late_wide:
        # 남은 넓은 벡터가 있으면 기본 자리는 이미 찼다(`_wide_room` 이 0 이 될 때까지 채웠다) — 빈 자리 채움이 필요 없다
        _mcdc_vectors.extend(_mcdc_late_wide)
        _mcdc_report["selected_inputs"] = (_mcdc_vectors[:_mcdc_base_n] + list((_mcdc_ext or {}).get("vectors") or [])
                                           + _mcdc_late_wide)
    _mcdc_roles_ext = _mcdc_vector_roles({"decisions": _mcdc_ext["decisions"]}) if _mcdc_ext else {}

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
        # (R82) 쓰기 전 값으로만 더한 입력(함수가 읽지 않고 쓴다)은 단독 경계로 움직이지 않는다 — 덮이는 값이라 극값이 가르는 것이
        #   없다. 쓰기를 드러내는 값은 동작 시나리오 탐색(쓰기 노출)이 고른다
        # (review R82 W4) and they do not make a unit 'two inputs or more': BV_MIN / BV_MAX already move a lone read input
        if len([v for v in input_vars if v not in _prior_inputs]) >= 2:
            for t_idx in range(len(_toggle_vars)):
                if t_idx < len(_design_toggles) and len(_design_inputs) < 2:
                    continue   # (R19 리뷰 R2 W2') 설계 입력이 하나면 BV_MIN/BV_MAX 가 이미 그 단독 변경이다
                if _toggle_vars[t_idx] in _prior_inputs:
                    continue
                for side in ("min", "max"):
                    # 조건 조합(앞 4개)이 이미 만든 (변수, 방향): 짝수 번째=min, 홀수 번째=max.
                    if t_idx < _cond_count and side == ("min" if t_idx % 2 == 0 else "max"):
                        continue
                    strategies.append((f"OAT_{t_idx}_{side.upper()}", f"_oat_{t_idx}_{side}"))

    # Pre-compute clamp/guard analysis once (avoid repeated DFS per strategy)
    check_vars = _design_out_list or input_vars
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
    # (R86) also when the unit has added inputs: the reference-scale document on the extension's columns holds them at the
    #   extended block's fixed value (`reference_unit_sequences`) — before R86 a reference-scale unit had none
    if extended or _added_inputs:
        from generators.boundary_rows import blank_fill
        _fill_domains = {v: d for v, d in _boundary_domains(unit, input_vars, var_types, var_bounds,
                                                            set(_unknown_vars), _domains).items()
                         if var_types.get(v) == _ENUM_TYPE or _declared(v)}
        _fill_all = blank_fill(_fill_domains, {v: m for v in _fill_domains
                                               if isinstance(m := (var_bounds.get(v) or {}).get("mid"), int)
                                               and not isinstance(m, bool)})
        # (R82) a write's prior value only: its fixed value differs from every value the function writes there
        #   (`_prior_fill_overrides` — the boundary rows' fill takes the same values, review R82 I-R5-2)
        _moved, _collide = _prior_fill_overrides(unit, _fill_all, _fill_domains, var_bounds)
        _sri = unit.get("source_read_inputs")
        if isinstance(_sri, dict):
            # (review R82 I-R5-3 · I-R5-4) what the rows' fixed value is and why — the latest generation's, not a book
            _sri.pop("prior_fixed_values", None)
            _sri.pop("prior_fixed_values_collide", None)
            if _moved:
                _sri["prior_fixed_values"] = {v: {"from": _fill_all[v], "to": x} for v, x in sorted(_moved.items())}
            if _collide:
                _sri["prior_fixed_values_collide"] = sorted(_collide)
        _fill_all.update(_moved)

    sequences: List[Dict[str, Any]] = []
    _fixed_of: Dict[int, frozenset] = {}   # (R85 리뷰 C-R2-1) row id → the added inputs this row holds at a fixed value
    # (R85) 카탈로그 행은 모두 만든다 — 정본 규모 문서의 행 수(`max_seq`)는 아래 정본 규모 블록이 지킨다
    for idx, (strat_name, bound_key) in enumerate(strategies):
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
        _fixed_read = [v for v in _fixed if v not in _prior_inputs]
        _fixed_prior = [v for v in _fixed if v in _prior_inputs]
        if _fixed_read:
            desc_lines.append("소스가 읽어 더한 입력(설계서 입력 표 밖 · 이 행에선 고정값): "
                              + ", ".join(f"{v}={inp_vals[v]}" for v in _fixed_read))
        if _fixed_prior:
            # (review R82 I-R5-5) the function writes these, it does not read them — the call's prior value
            desc_lines.append("쓰기 전 값(함수가 쓰는 객체의 호출 전 값 · 이 행에선 고정값): "
                              + ", ".join(f"{v}={inp_vals[v]}" for v in _fixed_prior))
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
        else:
            sequences[-1]["catalogue_slot"] = idx   # (R85 리뷰 I-7) 기준 행 후보의 동률 순서 — 만든 자리에서 단다
        if _fixed:
            _fixed_of[id(sequences[-1])] = frozenset(_fixed)

    # (R85) 정본 규모 블록 — 행 수는 예전 정본 규모 문서 그대로(`min(상한, 카탈로그 수)`; 확장은 기본 상한으로 같은 블록을
    #   만든다), 그 안을 MC/DC · switch · 루프 · 부수효과 행 → 코드 기준 행 → 나머지 카탈로그 행 순으로 채운다. 코드 기준 탐색은
    #   설계 입력 · 설계 출력 목록 위에서 돈다(두 프로파일이 같은 행 — R75).
    # (리뷰 R85 I5) 설계 출력이 없는 함수는 부수효과 행처럼 간접 전역을 관측한다 — 아니면 코드 기준 행이 아무것도 보지 않는다
    _code_ctx = {"input_vars": list(_design_inputs),
                 "output_vars": list(_design_out_list or (indirect_vars if _design_inputs else [])),
                 "var_types": dict(var_types), "var_bounds": dict(var_bounds), "unknown": sorted(_unknown_vars),
                 "declared": sorted(v for v in _design_inputs if _declared(v) and not _is_pointer_decl(v)),
                 "enum_sets": dict(_domains) if _pointee_domains else None}
    # (R86) the reference-scale document on the extension's columns (`reference_unit_sequences`) holds the added inputs
    #   of its code rows at the same fixed value as the extended block — before R86 it had no added inputs (empty)
    _added_fill = {v: _format_test_value(_fill_all[v], var_types.get(v, "uint8_t"))
                   for v in _added_inputs if v in _fill_all}
    _ref_cap = reference_cap if extended else max_seq
    sequences = _reference_scale_block(
        unit, sequences, _base_strategy_count,
        _base_strategy_count if _ref_cap is None else min(_ref_cap, _base_strategy_count), _code_ctx, extended,
        _added_fill, max_seq if extended else None, frozenset(_prior_inputs), _fixed_of)
    if not extended or boundary_rows:
        # the cache serves the rounds of one extended generation (`extended_unit_sequences` pops it at the end); a
        #   reference-scale or a final extended call drops it here (리뷰 R85 I-8)
        unit.pop("_code_rows_cache", None)

    # 행 상한(`strategies[:max_seq]`)을 **적용한 뒤** 쌍을 다시 검증한다 — 한쪽 행만 남은 쌍은 `truncated` 로 공시되고
    # 커버리지 주장에서 빠진다. MC/DC 행끼리만 묶는다(같은 입력의 BV 행을 쌍 구성원으로 잡으면 설계 근거가 섞인다).
    # (R23) 같은 TC 안에서 입력이 앞 행과 똑같은 행 — 기대값도 같아(결정적 oracle) 정보가 없다. 확장 전략 행(OAT·기본 자리를
    #   넘는 SWITCH/GLOBAL)은 근거 계산 전에 빼고, 정본 규모 카탈로그 행은 R75 포함 관계 때문에 두되 센다. MC/DC 행은 쌍이 벡터로
    #   행을 찾으므로, 경계·채움 행은 만들 때 이미 겹침을 피하므로 대상이 아니다. ⚠ finalize **앞**에서 한다 — finalize 가 쌍에
    #   행 번호(`seq_a`/`seq_b`)를 적어 두므로, 뒤에서 번호를 다시 매기면 MCDC Design 시트가 엉뚱한 행을 가리킨다(리뷰 R1 C1).
    sequences = _drop_duplicate_rows(unit, sequences, extended)
    # (리뷰 R85 C1) 정본 규모 예산이 작으면 확장 문서의 MC/DC 행이 `CATALOG_MCDC_<n>` 이다 — 여전히 그 벡터의 행이다
    _mcdc_rows = [s for s in sequences if _catalog_name(s.get("strategy")).startswith("MCDC_")]
    # (R2c) 함수 실행 모델로 설계한 결정(`evaluation=source_path`)은 행 입력으로 oracle 을 다시 돌려 검증한다 — unit 필요.
    if _mcdc_ext:
        # (R58) 각 설계를 자기 벡터 행으로만 검증한다 — finalize 는 받은 행의 `mcdc_design` 기록을 비우고 다시 쓰므로 두 호출이
        #   같은 행을 받으면 뒤 호출이 앞 호출의 기록을 지운다(리뷰 R58 W3 변이 M1: 기본 행이 쌍 기록을 잃었다). 경로 설계
        #   결정의 재실행은 그 설계의 unit 으로.
        _ext_ids = {id(d) for d in _mcdc_ext["decisions"]}
        finalize_mcdc_design(dict(_mcdc_report, decisions=[d for d in _mcdc_report["decisions"] if id(d) not in _ext_ids]),
                             [s for s in _mcdc_rows if not _mcdc_second(s)], _mcdc_unit)
        finalize_mcdc_design(dict(_mcdc_ext["report"], decisions=_mcdc_ext["decisions"]),
                             [s for s in _mcdc_rows if _mcdc_second(s)], _mcdc_ext["unit"])
        _mcdc_report["summary"] = mcdc_report_summary(_mcdc_report)
    else:
        finalize_mcdc_design(_mcdc_report, _mcdc_rows, _mcdc_unit)
    if _added_inputs:
        # (리뷰 R2 W3') 설계 입력 목록 위의 MC/DC 라 더한 입력을 읽는 결정은 거절된다 — 확장 문서엔 그 열이 있으니 "입력 목록 밖"
        #   이라 쓰면 거짓이다. 사유를 바꿔 적는다. (R58) 2차 설계가 그 결정을 맡으면 사유는 2차 설계의 것이고, 이 문구는 2차
        #   설계가 실패했을 때만 남는다.
        _added_set = set(_added_inputs)
        for _d in _mcdc_report.get("decisions") or []:
            _r = str(_d.get("reason") or "")
            if _r.startswith("decision_variable_not_in_unit_inputs:") and _r.split(":", 1)[1] in _added_set:
                _d["reason"] = "decision_reads_source_read_input_not_designed:" + _r.split(":", 1)[1]
    for _row in _mcdc_rows:
        # (리뷰 C1) "독립 영향 쌍" 은 **두 행이 모두 남아 재검증을 통과한** 쌍(`seq["mcdc_design"]`)에만 쓴다. 짝 행이 잘렸거나
        # 무효가 된 벡터는 그 사실을 라벨에 적는다 — 예전엔 절단 전 라벨이 남아 MCDC Design 시트(truncated)와 모순됐다.
        _is_ext = _mcdc_second(_row)
        _roles = (_mcdc_roles_ext if _is_ext else _mcdc_roles).get(
            _mcdc_vector_key({k: _row["inputs"].get(k) for k in _row["inputs"]}), [])
        _lines = str(_row.get("description") or "").split("\n")
        _lines[0] = _mcdc_vector_label(_row.get("mcdc_design") or [],
                                       [r["pair"].get("retained_status", "") for r in _roles])
        if str(_row.get("strategy") or "").startswith(CATALOG_PREFIX):
            _lines[0] = _DISPLACED_NOTE + _lines[0]   # (R85 리뷰 I-R3-3) the label rewrite kept the displaced note
        if _is_ext:
            # (R58) 설계서 입력 표 밖 입력(소스가 읽는 전역)까지 움직여 찾은 쌍 — 정본 규모 문서엔 없는 행이다
            _lines[0] += " · 소스가 읽어 더한 입력까지 쓴 설계(확장)"
        _blank = [v for v in input_vars if v not in _row["inputs"] and v not in _added_set_all]
        _blank_added = [v for v in input_vars if v not in _row["inputs"] and v in _added_set_all and v not in _prior_inputs]
        _blank_prior = [v for v in input_vars if v not in _row["inputs"] and v in _added_set_all and v in _prior_inputs]
        if _blank:
            # (R81) 결정이 읽지 않고 도메인도 모르는 입력은 비운 칸이다 — 값이 없다는 것을 행에서 말한다.
            _lines[0] += f" · 설계 밖 입력(공란, 결정 무관·도메인 미상): {', '.join(_blank)}"
        if _blank_added:
            # (review R86 I-R2-7) a source-read input has a declared domain — blank because the vector names only the
            #   inputs its decision reads (the extended document's fill rows give it the fixed value)
            _lines[0] += f" · 소스가 읽어 더한 입력(공란, MC/DC 벡터는 결정이 읽는 입력만): {', '.join(_blank_added)}"
        if _blank_prior:
            # (review R86 I-R3-2) the function writes these — the call's prior value (R82 I-R5-5 wording)
            _lines[0] += f" · 쓰기 전 값(공란, MC/DC 벡터는 결정이 읽는 입력만): {', '.join(_blank_prior)}"
        _row["description"] = "\n".join(_lines)
    if extended:
        # (R19) MC/DC 벡터가 비운 결정 무관 입력을 채운 동반 행(벡터 행·쌍 주장은 그대로). 선택 확장이라 실패해도 문서는 만든다.
        try:
            _append_mcdc_fill_rows(unit, sequences, input_vars, output_vars, var_types, _fill_all)
        except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
            _logger.warning("SUTS MC/DC 채움 행 실패(%s): %s", unit.get("name"), exc, exc_info=True)
            sequences[:] = [s for s in sequences if not str(s.get("strategy") or "").startswith(MCDC_FILL_PREFIX)]
            unit["mcdc_fill"] = {"error": type(exc).__name__}
    # 확장 행들의 탐색 문맥 — 동작 시나리오(R78) · 경계(R15) · 강건성(R31) · 출력 관측 쌍(R60)이 같은 도메인을 본다
    ctx = {"input_vars": list(input_vars), "output_vars": list(output_vars), "var_types": dict(var_types),
           "var_bounds": dict(var_bounds), "unknown": sorted(_unknown_vars),
           # (R31 review W5) 타입이 선언에서 온 입력 — 추측 타입의 폭으로 "타입 안" 을 판정하지 않는다
           "declared": sorted(v for v in input_vars if _declared(v) and not _is_pointer_decl(v)),
           # (R40 리뷰 2차 I-d) 포인터 대상의 열거자 값 집합까지 — 경계 행도 BV·MC/DC 행과 같은 도메인으로
           "enum_sets": dict(_domains) if _pointee_domains else None}
    if extended:
        # (R78) 동작 시나리오 행 — 근거를 붙이기 **전**(다른 행과 한 번에 도출)이고 R19 회차마다 다시 찾는다: 탐색이 닿으려다
        #   입력 목록 밖 객체를 읽었으면(`needed_inputs`) 입력 보완(`complete_source_read_inputs`)이 그 이름을 더하고 다음
        #   회차의 탐색이 그 입력까지 움직인다. 선택 확장이라 실패해도 문서는 만든다(그 unit 만 사유를 남긴다).
        _n_before = len(sequences)
        try:
            _append_scenario_rows(unit, sequences, ctx)
        except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
            _logger.warning("SUTS 동작 시나리오 행 실패(%s): %s", unit.get("name"), exc, exc_info=True)
            del sequences[_n_before:]
            unit["scenario_rows"] = {"error": type(exc).__name__, "rows": 0}
    # (R80) 행의 실행이 쓴 객체도 받는다(`seq["source_written"]`) — 출력 목록 밖 쓰기 소견(두 프로파일) · 확장의 기대 열 보완
    sequences = apply_sequence_evidence(unit, sequences, written=True)
    if not extended:
        return sequences
    sequences = _prune_mcdc_fill_rows(unit, sequences)
    # (R15) 경계 행 — 확장 프로파일에만. 출력이 바뀌는 인접 입력 두 값을 행으로 **더한다**(기존 행은 옮기지 않는다, R4b 교훈).
    #   `boundary_rows=False` 면 탐색에 쓸 문맥만 남기고 호출자가 마지막에 한 번 붙인다(`append_boundary_rows`, R19 리뷰 W6).
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
                          set(ctx["unknown"]), ctx.get("enum_sets"))
    # (R31) 설계 범위 밖 강건성 행 — 경계 행 뒤에. 선택 확장이라 실패해도 문서는 만든다(그 unit 만 사유를 남긴다).
    m = len(sequences)
    try:
        _append_robustness_rows(unit, sequences, ctx["input_vars"], ctx["output_vars"], ctx["var_types"],
                                ctx["var_bounds"], set(ctx["unknown"]), set(ctx.get("declared") or ()))
    except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
        _logger.warning("SUTS 강건성 행 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        del sequences[m:]
        unit["robustness_rows"] = {"error": type(exc).__name__, "rows": 0}
    # (R60) 출력으로 드러나는 MC/DC 쌍 — 강건성 행 뒤에. 선택 확장이라 실패해도 문서는 만든다.
    k = len(sequences)
    try:
        _append_observable_mcdc_rows(unit, sequences, ctx)
    except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
        _logger.warning("SUTS 출력 관측 MC/DC 쌍 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        del sequences[k:]
        unit["observable_mcdc"] = {"error": type(exc).__name__, "rows": 0}
        for decision in (unit.get("mcdc_design") or {}).get("decisions") or []:
            for pair in decision.get("pairs") or []:
                pair.pop("observable", None)
    # (R78) 설계 범위 밖 동작 시나리오 — **마지막**에(경계 · 강건성 · 출력 관측 쌍은 이 행들 없이 돈다 — 리뷰 R78 C1 · W6).
    #   선택 확장이라 실패해도 문서는 만든다(그 unit 만 사유를 남긴다).
    j = len(sequences)
    try:
        _append_scenario_fi_rows(unit, sequences, ctx)
    except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
        _logger.warning("SUTS 설계 범위 밖 동작 시나리오 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        del sequences[j:]
        if isinstance(unit.get("scenario_rows"), dict):
            unit["scenario_rows"]["outside_design_error"] = type(exc).__name__
    # (R83) 피호출 값 구별 행 — 맨 끝에(다른 탐색은 이 행들 없이 돈다; 어느 행이든 출처가 될 수 있다). 선택 확장이라 실패해도
    #   문서는 만든다(그 unit 만 사유를 남긴다).
    h = len(sequences)
    try:
        _append_stub_apart_rows(unit, sequences, ctx)
    except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
        _logger.warning("SUTS 피호출 값 구별 행 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        del sequences[h:]
        unit["stub_apart"] = {"error": type(exc).__name__, "rows": 0}
    # (R84) 결함 전파 행 — 맨 끝에(다른 탐색 · 동반 행은 이 행들 없이 돈다; 모든 행이 이미 있는 행이다). 선택 확장이라 실패해도
    #   문서는 만든다(그 unit 만 사유를 남긴다).
    g = len(sequences)
    try:
        _append_propagation_rows(unit, sequences, ctx)
    except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
        _logger.warning("SUTS 결함 전파 행 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        del sequences[g:]
        unit["propagation_rows"] = {"error": type(exc).__name__, "rows": 0, "fi_rows": 0}
    if len(sequences) > n:
        sequences[n:] = apply_sequence_evidence(unit, sequences[n:], written=True)
    if (unit.get("observable_mcdc") or {}).get("searched"):
        try:
            _confirm_observable_rows(unit, sequences)
        except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
            _logger.warning("SUTS 출력 관측 MC/DC 쌍 확인 실패(%s): %s", unit.get("name"), exc, exc_info=True)
            unit["observable_mcdc"]["confirm_error"] = type(exc).__name__
    _note_rows_equal_to_code_rows(unit, sequences)
    return sequences


_SAME_AS_CODE_NOTE = "정본 규모 코드 기준 행 {name} 와 입력이 같음 — 확장 탐색은 코드 기준 행 없이 돈다(R85 전과 같은 확장 행)"


def _note_rows_equal_to_code_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> None:
    """(리뷰 R85 W-R4-1) 확장 행 중 정본 규모 코드 기준 행과 입력이 같은 행 — 확장 탐색은 코드 기준 행이 없을 때처럼 돌기 때문에
    (`_search_rows`, R85 측정: 섞자 kill 34 를 잃었다) 같은 벡터를 다시 찾을 수 있다. 빼지 않는다 — 경계 행 설명(기준 행) ·
    피호출 값 구별 행의 출처 · 출력 관측 쌍이 그 행을 가리킨다; 행 설명에 그 코드 기준 행을 적고 unit 기록
    (`reference_code_rows.extension_same_inputs`)이 센다(R23: 앞 행과 같은 행은 정보가 없다 — 침묵하지 않는다)."""
    code: Dict[str, str] = {}
    for s in sequences:
        name = str(s.get("strategy") or "")
        if name.startswith(CODE_PREFIX):
            code.setdefault(json.dumps(s.get("inputs") or {}, sort_keys=True, default=str), name)
    n = 0
    for s in sequences:
        if not code or s.get("tc_profile") != TC_PROFILE_EXTENDED:
            continue
        twin = code.get(json.dumps(s.get("inputs") or {}, sort_keys=True, default=str))
        if not twin:
            continue
        n += 1
        if s.get("same_inputs_as_code_row") != twin:
            s["same_inputs_as_code_row"] = twin
            s["description"] = (str(s.get("description") or "") + "\n" + _SAME_AS_CODE_NOTE.format(name=twin)).lstrip("\n")
    rec = unit.get("reference_code_rows")
    if isinstance(rec, dict):
        rec["extension_same_inputs"] = n


# (R83) 피호출 값 구별 행 — 두 피호출 stub 이 같은 값을 돌려주는 행은 그 값을 받은 출력에서 어느 피호출의 값이 갔는지 · 어느
#   갈래를 탔는지 가르지 못한다(KJPDS02_PV `s_FanRecircurationCheck`: 창 닫힘 · 열림 보정 단계를 돌려주는 두 stub 이 모든 행에서
#   같은 값(0 · 127)이라 `u8t_WindowsClosed == u8g_ON` 을 `!=` 로 바꿔도 출력이 같았다; HDPDM01 `s_ApiOut_u8bit_DataUpdate_A`:
#   두 변환 stub 이 같은 값이라 `u8t_Temp = u8s_ApiOut_Vsup_Conv();` 가 빠져도 같았다). 정본은 stub 마다 다른 값을 둔다. 기존 행의
#   값은 바꾸지 않는다(리뷰 R83 C1 — 확장 문서는 기본 문서의 행을 같은 값으로 담는다, R75): 같은 값을 받은 stub 을 서로 다른 값으로
#   옮긴 **동반 행**을 더한다 — 같은 피호출들이 불리는(같은 경로의) 행이고 갈라 놓은 stub 을 그 경로가 부를 때만, 불리는 피호출
#   묶음마다 하나.
STUB_APART_PREFIX = "STUB_APART_"
MAX_STUB_APART_ROWS = 8        # companion rows per function
MAX_STUB_APART_SOURCES = 64    # source rows tried per function (two oracle runs each)


def _apart_value(domain: Any, value: int, step: int, taken: set) -> Optional[int]:
    """(R83) A value of ``domain`` other than ``value`` and every value in ``taken``: in a range the nearest by ``step``
    (``value+step``, ``value-step``, then a step wider); in a value list the next members after ``value`` — the design's
    values only, never one outside the list (review R83 W2); None when the domain is unknown or has none left. ``step``
    0: ``value`` itself when the domain holds it (a membership test)."""
    if isinstance(domain, tuple) and len(domain) == 2 and all(isinstance(x, int) for x in domain):
        lo, hi = domain
        if step == 0:
            return value if lo <= value <= hi and value not in taken else None
        for d in range(step, step + 8):
            for x in (value + d, value - d):
                if lo <= x <= hi and x not in taken:
                    return x
        return None
    if isinstance(domain, (list, set, frozenset)):
        vals = sorted({int(v) for v in domain if isinstance(v, int) and not isinstance(v, bool)})
        if step == 0:
            return value if value in vals and value not in taken else None
        order = vals[vals.index(value) + 1:] + vals[:vals.index(value)] if value in vals else vals
        return next((x for x in order if x not in taken), None)
    return None


def _run_path(r: Dict[str, Any]) -> Tuple[tuple, tuple]:
    """(R83) The path of a modeled run as far as a row shows it: the callees it calls (stubs) and the objects it writes
    (HDPDM01 `s_ApiOut_u8bit_DataUpdate_A` calls the same three stubs on every row — the valid arm writes the outputs, the
    invalid one the error count) — with whether each written value is known (review R83 I-R4-3: a move that flips a
    decision between two arms writing the same object turns the value known or unknown)."""
    return (tuple(sorted(r.get("stubs") or ())),
            tuple(sorted((str(k), bool(v)) for k, v in (r.get("written") or {}).items())))


def _append_stub_apart_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]], ctx: Dict[str, Any]) -> None:
    """(R83, 확장 프로파일) 피호출 값 구별 행. 행 중(기준 행 순서 — FI 행 · 설계 범위 밖 값을 가진 행은 출처가 아니다, R31 기준 행과
    같은 규칙) 피호출 stub 반환값 둘 이상이 같은 값(각자 경계 행 도메인 안)인 행마다, 그 묶음의 첫 stub 은 두고 나머지를 서로 다른
    값으로 옮긴 벡터(`_apart_value` — 도메인 안, 값 목록이면 목록의 값)를 원래 행과 함께 원본 코드 모델로 돌려, (1) 같은 경로
    (`_run_path` — 부르는 피호출 · 쓰는 객체)이고 (2) 갈라 놓은 묶음이 알려 주는 것이 있으면 — 이 경로가 그 묶음의 stub 을 둘
    이상 부르거나, 하나를 부르고 다른 stub 을 다른 행의 경로가 부른다(갈래가 바뀌면 그 값이 나온다) — 동반 행으로 더한다. 경로마다
    하나(`MAX_STUB_APART_ROWS` 상한, 출처 후보 `MAX_STUB_APART_SOURCES` 상한, 16 개씩 돌리고 행 상한이 차면 멈춘다). enum · 타입을
    모르는 stub 은 옮기지 않는다. 기존 행은 바꾸지 않는다. 기대값은 뒤의 oracle 이 모든 행과 똑같이 도출한다. 요약은
    `unit["stub_apart"]` — 출처 후보는 행 · 갈라도 알려 주는 것 없음 · 경로가 바뀜 · 도출 못 함 · 같은 경로에 이미 있음 · 행 상한
    중 하나로 끝난다(합이 출처 수)."""
    from generators.boundary_rows import _as_int
    from generators.c_source_oracle import evaluate_outputs
    var_types = ctx["var_types"]
    unknown = set(ctx.get("unknown") or ())
    stubs = [v for v in ctx["input_vars"] if str(v).endswith(f"() {_RETURN_VAR}")
             and var_types.get(v) != _ENUM_TYPE and v not in unknown]
    report: Dict[str, Any] = {"stubs": len(stubs), "sources": 0, "rows": 0, "uninformative": 0, "path_changed": 0,
                              "underived": 0, "same_path": 0, "cut_rows": 0, "cut_sources": 0, "duplicates": 0,
                              "no_value_stubs": 0}
    unit["stub_apart"] = report
    if len(stubs) < 2:
        report["status"] = "fewer_than_two_stubs"
        return
    var_bounds = ctx["var_bounds"]
    domains = _boundary_domains(unit, ctx["input_vars"], var_types, var_bounds, unknown, ctx.get("enum_sets"))
    outputs = _scenario_outputs(ctx, _search_rows(sequences))
    src = unit.get("bounds_source") or {}
    # (review R83 W-R2-1) the design ranges a source row stays inside — R31's base rule (`_append_robustness_rows`)
    ranged = [v for v in ctx["input_vars"]
              if src.get(v) in ("uds_range", "hsis_range", "uds_values") and v not in unknown
              and isinstance((var_bounds.get(v) or {}).get("min"), int)
              and isinstance((var_bounds.get(v) or {}).get("max"), int)]

    def ints(inputs: Dict[str, Any]) -> Optional[Dict[str, int]]:
        out: Dict[str, int] = {}
        for k, v in inputs.items():
            n = _as_int(v)
            if n is None:
                return None
            out[k] = n
        return out

    existing = {tuple(sorted(x.items())) for s in _search_rows(sequences) if (x := ints(s.get("inputs") or {})) is not None}
    cands: List[Tuple[Dict[str, Any], Dict[str, int], Dict[str, int], Dict[str, Tuple[int, int]], List[set]]] = []
    for s in _base_order(_search_rows(sequences)):
        if resolve_seq_test_method(s.get("strategy")) == _METHOD_FI:
            continue                        # a robustness / FI row's point is its out-of-range value
        vec = ints(s.get("inputs") or {})
        if vec is None or any(u in vec and not var_bounds[u]["min"] <= vec[u] <= var_bounds[u]["max"] for u in ranged):
            continue
        groups: Dict[int, List[str]] = {}
        for k in stubs:
            # (a stub value outside its domain — a `BV_*_INV` row — is no value to tell apart)
            if k in vec and _apart_value(domains.get(k), vec[k], 0, set()) == vec[k]:
                groups.setdefault(vec[k], []).append(k)
        if all(len(g) < 2 for g in groups.values()):
            continue
        if len(cands) >= MAX_STUB_APART_SOURCES:
            report["cut_sources"] += 1
            continue
        new, taken, moved = dict(vec), {vec[k] for k in stubs if k in vec}, {}
        apart: List[set] = []   # the colliding groups, each told apart on its own (review R83 W-R3-2)
        for value, members in groups.items():
            if len(members) > 1:
                apart.append(set(members))
            for step, k in enumerate(members[1:], 1):
                x = _apart_value(domains.get(k), value, step, taken)
                if x is None:
                    report["no_value_stubs"] += 1
                    continue
                new[k] = x
                taken.add(x)
                moved[k] = (value, x)
        if not moved:
            continue
        key = tuple(sorted(new.items()))
        if key in existing:
            report["duplicates"] += 1
            continue
        existing.add(key)
        cands.append((s, vec, new, moved, apart))
    report["sources"] = len(cands)
    if not cands:
        return
    # the source rows run first (review R83 I-R3-1): which stubs the rows' runs call — the arm a changed decision may
    #   take — is known before any move is judged, whatever the order; a move's own (virtual) run is no row's
    sources = evaluate_outputs(unit, [c[1] for c in cands], [list(outputs)] * len(cands), written=True)
    called_by_rows: set = {str(x) for r in sources for x in r.get("stubs") or ()}
    for s in _search_rows(sequences):   # rows that already have evidence say which stubs their runs called (R14 `stubs`)
        for ev in (s.get("expected_evidence") or {}).values():
            if isinstance(ev, dict):
                called_by_rows.update(str(x) for x in ev.get("stubs") or ())
    paths: set = set()
    suffix = f"() {_RETURN_VAR}"

    def derived(r: Dict[str, Any]) -> set:
        return {o for o, x in (r.get("outputs") or {}).items() if "value" in (x or {})}

    for start in range(0, len(cands), 16):
        chunk = cands[start:start + 16]
        if report["rows"] >= MAX_STUB_APART_ROWS:
            report["cut_rows"] += len(chunk)
            continue
        moves = evaluate_outputs(unit, [c[2] for c in chunk], [list(outputs)] * len(chunk), written=True)
        for i, (s, _vec, new, moved, apart) in enumerate(chunk):
            ra, rb = sources[start + i], moves[i]
            # (review R83 W-R3-1) a source that forks (its path is a union, its stubs too) or derives nothing, or a move
            #   that loses an output the source derived, makes no companion — its expectation would not stand
            # (review R83 I-R4-5) a failed record of the written objects leaves no path to compare — not a weaker key
            if ra.get("status") != "supported" or rb.get("status") != "supported" or int(ra.get("paths") or 1) > 1 \
                    or ra.get("written_error") or rb.get("written_error") \
                    or not derived(ra) or not derived(ra) <= derived(rb):
                report["underived"] += 1
                continue
            path = _run_path(ra)
            if path != _run_path(rb):
                report["path_changed"] += 1   # a moved stub decided the path — no longer the same row told apart
                continue
            # (review R83 I-R2-1 · W-R3-2) what telling a group apart shows, group by group: two of its stubs this path
            #   calls, or one it calls and another a row's path calls (the arm a changed decision takes — `doors() ==
            #   ON` → the closed level, the open level apart); a group no path calls but one stub of shows nothing
            def informative(group: set) -> bool:
                # (review R83 W-R4-1) by the values the move left: a stub with no value to move stays equal to the one
                #   it collided with — telling those two apart did not happen
                here = {k for k in group if k[:-len(suffix)] in path[0]}
                there = {k for k in group - here if k[:-len(suffix)] in called_by_rows}
                return any(new[a] != new[b] for a in here for b in here | there if a != b)

            if not any(informative(g) for g in apart):
                report["uninformative"] += 1
                continue
            if path in paths:
                report["same_path"] += 1
                continue
            if report["rows"] >= MAX_STUB_APART_ROWS:
                report["cut_rows"] += 1
                continue
            paths.add(path)
            oa, ob = ra.get("outputs") or {}, rb.get("outputs") or {}
            # (review R83 I-R4-3) an output only the move derives changed too
            changed = [o for o in outputs if "value" in (ob.get(o) or {})
                       and ("value" not in (oa.get(o) or {}) or oa[o]["value"] != ob[o]["value"])]
            blank = [v for v in ctx["input_vars"] if v not in (s.get("inputs") or {})]
            shown = ", ".join(f"{k}={a}→{x}" for k, (a, x) in list(moved.items())[:4]) + (
                f" 외 {len(moved) - 4}" if len(moved) > 4 else "")
            sequences.append({
                "seq_num": len(sequences) + 1,
                "inputs": {k: (_format_test_value(new[k], var_types.get(k, "uint8_t")) if k in moved else v)
                           for k, v in (s.get("inputs") or {}).items()},
                "expected": {o: f"{VERIFY_PREFIX} stub_apart" for o in outputs},
                "strategy": f"{STUB_APART_PREFIX}{report['rows']}", "tc_profile": TC_PROFILE_EXTENDED,
                "description": (f"피호출 값 구별 행: 시퀀스 {s.get('seq_num')}({s.get('strategy')})에서 같은 값이던 피호출 stub "
                                f"반환값을 서로 다른 값으로 옮긴 행 — {shown}. 같은 경로(부르는 피호출 · 쓰는 객체와 그 값을 아는지가 "
                            "같다 — 반환값은 경로에 넣지 않는다)에서 "
                                + (f"출력 {', '.join(changed[:4])} 이 원래 행과 달라진다" if changed else
                                   "쓴 출력은 원래 행과 같고, 이 경로가 부르는 stub 의 값이 다른 갈래가 부르는 stub 과 갈린다")
                                + ": 원래 행으로는 그 출력에 어느 피호출의 값이 갔는지 · 어느 갈래를 탔는지 가를 수 없었다(정본도 "
                                "stub 마다 다른 값을 둔다). 원래 행은 그대로다"
                                + (f" · 원래 행이 비운 칸은 그대로 비움: {', '.join(blank[:4])}"
                                   + (f" 외 {len(blank) - 4}" if len(blank) > 4 else "") if blank else "")
                                + " — 기대값은 소스 oracle 도출 · 미실행"),
                "stub_apart": {"from_sequence": s.get("seq_num"), "moved": {k: [a, x] for k, (a, x) in moved.items()},
                               "outputs_changed": changed[:8]},
            })
            report["rows"] += 1


def summarize_stub_apart(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """(R83) unit 보고서 합계 — 품질 보고서 `stub_apart`(생성 공시가 읽는다)."""
    reports = [u.get("stub_apart") for u in units if isinstance(u.get("stub_apart"), dict)]
    out: Dict[str, Any] = {k: sum(int(r.get(k) or 0) for r in reports)
                           for k in ("sources", "rows", "uninformative", "path_changed", "underived", "same_path",
                                     "cut_rows", "cut_sources", "duplicates", "no_value_stubs")}
    out.update(units_with_rows=sum(1 for r in reports if r.get("rows")),
               units_with_two_stubs=sum(1 for r in reports if int(r.get("stubs") or 0) >= 2),
               errors=sum(1 for r in reports if r.get("error")), cap_per_unit=MAX_STUB_APART_ROWS,
               sources_per_unit=MAX_STUB_APART_SOURCES)
    return out


# (R84) 결함 전파 행 — 결함이 드러나는 값(R79)으로 그 자리를 실행해도 바뀐 값이 출력까지 가지 않으면 그 결함은 보이지 않는다
#   (KJPDS02_PV, R83 뒤 정본도 생성도 죽이지 못한 변이 20: `ErrTm < u16g_MAX` 를 65535 로 실행했지만 다른 갈래가 쓰는 상태를
#   행이 이미 갖고 있었다 · `y = 0` 클램프가 `Diff = Assist - Start` 로 곱해지는데 둘이 같았다 · 경사/평상 전류 임계 입력을
#   행이 같은 값으로 두었다 · `EndStep < 0` 이어야 다른 팔이 다른 값 · 음수 나눗수 팔은 설계 범위 밖 값이어야 닿는데 그 탐색엔
#   노출 목표가 없었다(R79 리뷰 W3)). `scenario_rows.find_scenarios(propagate=True)` — 자리마다 그 값을 바꾼 실행(데이터 상태
#   섭동: 비교 뒤집기(경계 목표는 두 값이 같을 때만) · 쓰기 빼기 · `+` `-` `*` 오른쪽을 항등원 · `/` `%` 한 칸)과 원래 실행의
#   관측 출력이 달라지는 행. 설계 범위 안에서 먼저 찾고, 못 찾은 목표만 설계 범위 밖(선언 타입 · 열거자 밖)으로 넓혀 다시 —
#   설계 범위 밖 값이 남은 행은 FI(`PROPR_`). **맨 끝에** 더한다(기존 행 · 탐색은 그대로 — R75 · R80 교훈).
PROPAGATE_PREFIX = "PROP_"
PROPAGATE_FI_PREFIX = "PROPR_"
PROPAGATION_REPORT_KEYS = ("targets", "boundary", "flip", "write", "arith", "covered_before", "met_by_rows", "not_met",
                           "rows", "fi_rows", "duplicates", "local_best", "budget_cut", "unmodeled", "cut", "error_cut",
                           "refused", "infected_only", "runs", "perturbed_runs", "perturbed_refused",
                           "perturbed_budget", "steps", "checked_rows", "check_capped", "check_late", "check_steps",
                           "outside_design_check_capped", "outside_design_check_late",
                           "outside_design_inputs", "outside_design_searched", "outside_design_met")


def _propagation_row(sequences: List[Dict[str, Any]], row: Dict[str, Any], strategy: str, outputs: List[str],
                     var_types: Dict[str, str], outside: Dict[str, int], span: Dict[str, Any],
                     enums: Dict[str, Dict[str, Any]]) -> None:
    """(R84) 결함 전파 행 하나 — 무엇을 바꾸면 어느 출력이 달라지는지, 설계 범위 밖 값이 남았으면 그 값까지 적는다."""
    inputs = {k: _format_test_value(v, var_types.get(k, "uint8_t")) for k, v in row["inputs"].items()}
    kind, seen = row["target_kind"], row.get("exposure") or [None, None]
    at = f"{row['target_line']}행 `{row['target_text']}`"
    if kind == "boundary":
        what = f"경계 {at} 을 두 값이 같을 때({seen[0]} = {seen[1]}) 평가하고 그 조건이 결정을 가르는데, 그 비교 결과를 뒤집으면"
    elif kind == "flip":
        what = f"조건 {at} 이 결정을 가를 때(비교한 값 {seen[0]}, {seen[1]}) 그 조건을 뒤집으면"
    elif kind == "write":
        what = f"쓰기 {at} 가 이전 값 {seen[0]} 을 {seen[1]} 로 바꾸는데, 그 쓰기를 빼면"
    else:
        op = row.get("operator") or ""
        what = (f"연산 {at} 의 `{op}` 를 피연산자 {seen[0]}, {seen[1]} 로 계산하는데, "
                + ("오른쪽 피연산자를 항등원으로 두면(항 · 인수 누락)" if op in ("+", "-", "*") else "결과를 한 칸 옮기면"))
    changed = ", ".join(row.get("propagated") or [])
    body = (f"{what} 관측 출력 {changed} 이 달라진다 — 원본 코드 모델 실행을 그 자리의 값만 바꿔 한 번 더 돌려 비교했다(데이터 "
            "상태 섭동 · 측정 도구의 변이 목록은 쓰지 않는다; 같은 종류의 결함을 겨냥하므로 이 행으로 늘어난 변이 판별은 상수 "
            "변이로 따로 본다). 두 실행 모두 한 경로로(미정 분기 · 미정의 동작 없이) 돈다")
    if outside:
        # (review R84 W3) the search widens range and value-set inputs together: each value says what it is outside of
        def label(k: str, x: int) -> str:
            if k in enums:
                return _outside_label(enums[k], x)
            if isinstance(span.get(k), tuple):
                return f"설계 {span[k][0]}~{span[k][1]} 밖"
            return "설계 밖"
        shown = ", ".join(f"{k}={x}({label(k, x)})" for k, x in outside.items())
        kind_of = "열거자 밖 값" if set(outside) <= set(enums) else "설계 범위 밖"
        head = f"{kind_of} 결함 전파 시나리오: {body}. 설계 범위 안에서 먼저 찾은 뒤 넓혀 찾았고 남은 값: {shown}(FI · "
    else:
        head = f"결함 전파 시나리오: {body}("
    sequences.append({
        "seq_num": len(sequences) + 1, "inputs": inputs,
        "expected": {o: f"{VERIFY_PREFIX} propagation" for o in outputs},
        "strategy": strategy, "tc_profile": TC_PROFILE_EXTENDED,
        "description": head + f"이 행으로 처음 만족한 전파 목표 {row.get('exposures_met', 0)}개 · 소스 oracle 탐색 · 미실행)",
        "propagation": {**{k: row.get(k) for k in ("target_kind", "target_line", "target_text", "exposure", "operator",
                                                    "propagated")}, "outside_design": dict(outside)},
    })


def _append_propagation_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]], ctx: Dict[str, Any]) -> None:
    """(R84, 확장 프로파일) 결함 전파 행 — 위 주석. 설계 범위 안 탐색(`PROP_`) 뒤, 남은 목표가 있고 설계 범위가 선언 타입보다
    좁은 입력 · 열거자 밖 값을 가질 수 있는 값 목록 입력이 있으면 둘을 함께 넓혀 한 번 더(남은 밖 값이 있으면 `PROPR_` FI).
    요약 `unit["propagation_rows"]`(키 `PROPAGATION_REPORT_KEYS`) — 목표 = 이미 있던 행이 만족 + 이 단계의 행이 만족 + 못 만족
    (그 사유는 마지막 탐색의 것)."""
    report: Dict[str, Any] = {**dict.fromkeys(PROPAGATION_REPORT_KEYS, 0), "status": "", "budget_exhausted": False}
    unit["propagation_rows"] = report
    var_types = ctx["var_types"]
    domains = _scenario_domains(unit, ctx)
    outputs = _scenario_outputs(ctx, _search_rows(sequences))

    def existing_rows() -> List[Dict[str, Any]]:
        # the scenario rows first — distinct operating values make the better climb starts (`MAX_STARTS`)
        return [s.get("inputs") or {} for s in _scenario_rows_first(_search_rows(sequences))]

    def take(rep: Dict[str, Any], first: bool) -> None:
        for k in ("runs", "steps"):
            report[k] += int(rep.get("expose_" + k) or 0)
        for k in ("perturbed_runs", "perturbed_refused", "perturbed_budget", "checked_rows", "check_steps"):
            report[k] += int(rep.get("propagate_" + k) or 0)
        # (review R84 I-R3-2) the suite check's cuts and late confirmations per search — the first's late ones are in
        #   `covered_before`; the second's (rare: a row the first search's budget left unchecked) in `met_by_rows`
        for k in ("check_capped", "check_late"):
            report[k if first else "outside_design_" + k] += int(rep.get("propagate_" + k) or 0)
        report["duplicates"] += int(rep.get("expose_duplicates") or 0)
        report["budget_exhausted"] = report["budget_exhausted"] or bool(rep.get("expose_budget_exhausted"))
        if first:
            report.update(targets=int(rep.get("expose_targets") or 0), boundary=int(rep.get("expose_boundary") or 0),
                          flip=int(rep.get("expose_flip") or 0), write=int(rep.get("expose_write") or 0),
                          arith=int(rep.get("expose_arith") or 0),
                          covered_before=int(rep.get("expose_covered_before") or 0))
        # the not-met targets and why — the last search's (it saw every row before it)
        report.update(not_met=int(rep.get("expose_not_reached") or 0),
                      local_best=int(rep.get("expose_local_best") or 0),
                      budget_cut=int(rep.get("expose_budget_cut") or 0),
                      unmodeled=int(rep.get("expose_unmodeled") or 0), cut=int(rep.get("expose_cut") or 0),
                      error_cut=int(rep.get("expose_error_cut") or 0), refused=int(rep.get("expose_refused") or 0),
                      infected_only=int(rep.get("propagate_infected_only") or 0))
        report["met_by_rows"] = report["targets"] - report["covered_before"] - report["not_met"]

    start = len(sequences)
    existing = existing_rows()
    found = find_scenarios(unit, domains, outputs, existing, covered=existing, propagate=True)
    rep = found["report"]
    report["status"] = str(rep.get("status") or "")
    if report["status"] != "searched":
        return
    take(rep, True)
    for row in found["rows"]:
        _propagation_row(sequences, row, f"{PROPAGATE_PREFIX}{report['rows']}", outputs, var_types, {}, {}, {})
        report["rows"] += 1
    if not report["not_met"]:
        return
    # 설계 범위 밖 — 설계 범위가 선언 타입보다 좁은 입력 · 값 목록 입력의 열거자 밖 값(R78 · R80 과 같은 넓힘)
    wide = _design_widened(unit, domains, var_types)
    homes: Dict[str, Tuple[List[int], List[int]]] = {}
    try:
        singles = _single_value_enum_domains(unit, ctx, domains)
        enum_wide = _outside_enumerator_domains(unit, {**domains, **singles}, var_types, {}, ctx.get("enum_sets"), homes)
    except Exception as exc:  # noqa: BLE001 — (review R84 I1) the enum widening alone is lost, as in R80
        _logger.warning("SUTS 결함 전파 열거자 밖 값 준비 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        report["outside_design_enum_error"] = type(exc).__name__
        enum_wide = {}
    report["outside_design_inputs"] = len(set(wide) | set(enum_wide))
    if not (wide or enum_wide):
        return
    span: Dict[str, Any] = {k: (d if isinstance(d, tuple) else (d["min"], d["max"])) for k, d in domains.items() if k in wide}
    span.update({k: list(homes[k][0]) for k in enum_wide})
    var_bounds, src = ctx.get("var_bounds") or {}, unit.get("bounds_source") or {}
    info: Dict[str, Dict[str, Any]] = {}
    for k in enum_wide:
        b = var_bounds.get(k) or {}
        design: Any = None
        if src.get(k) in ("uds_range", "hsis_range") and isinstance(b.get("min"), int) and isinstance(b.get("max"), int):
            design = (b["min"], b["max"])
        elif src.get(k) == "uds_values":
            design = list(homes[k][0])
        info[k] = {"design": design, "enumerators": (homes[k][1][0], homes[k][1][-1])}
    # (review R84 W2) this step's own rows first — the suite check stops at a cap per target, and a target the first
    #   search met by a row listed last was searched again (a needless FI row, and wrong counts)
    before = sequences[:start]
    checked = [s.get("inputs") or {} for s in sequences[start:]] + \
        [s.get("inputs") or {} for s in _scenario_rows_first(_search_rows(before))]
    # (review R84 I-R2-4) the climb starts keep the scenario rows first (`existing_rows`)
    again = find_scenarios(unit, {**domains, **wide, **enum_wide}, outputs, existing_rows(), covered=checked,
                           home=span, propagate=True)
    rep2 = again["report"]
    if str(rep2.get("status") or "") != "searched":
        return
    report["outside_design_searched"] = int(rep2.get("expose_targets") or 0) - int(rep2.get("expose_covered_before") or 0)
    report["outside_design_met"] = int(rep2.get("expose_reached") or 0) - int(rep2.get("expose_covered_before") or 0)
    take(rep2, False)
    for row in again["rows"]:
        outside = {k: x for k, x in row["inputs"].items() if k in span and not _at_home(span[k], x)}
        if outside:
            _propagation_row(sequences, row, f"{PROPAGATE_FI_PREFIX}{report['fi_rows']}", outputs, var_types, outside,
                             span, info)
            report["fi_rows"] += 1
        else:
            _propagation_row(sequences, row, f"{PROPAGATE_PREFIX}{report['rows']}", outputs, var_types, {}, {}, {})
            report["rows"] += 1


def summarize_propagation_rows(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """(R84) unit 보고서 합계 — 품질 보고서 `propagation_rows`(생성 공시가 읽는다)."""
    reports = [u.get("propagation_rows") for u in units if isinstance(u.get("propagation_rows"), dict)]
    out: Dict[str, Any] = {k: sum(int(r.get(k) or 0) for r in reports) for k in PROPAGATION_REPORT_KEYS}
    out.update(units=len(units), searched=sum(1 for r in reports if r.get("status") == "searched"),
               units_with_rows=sum(1 for r in reports if r.get("rows") or r.get("fi_rows")),
               budget_exhausted=sum(1 for r in reports if r.get("budget_exhausted")),
               errors=sum(1 for r in reports if r.get("error")),
               # (review R84 W-R2-1) the enum widening failed alone — the unit kept its in-design rows
               enum_errors=sum(1 for r in reports if r.get("outside_design_enum_error")),
               not_searched=dict(Counter(str(r.get("status")).split(":", 1)[0] for r in reports
                                         if r.get("status") not in ("searched", None, "") and not r.get("error"))),
               cap_per_unit=_PROPAGATE_MAX_ROWS, check_per_target=_PROPAGATE_MAX_CHECK, atoms_cap=_SCENARIO_MAX_ATOMS,
               check_runs_cap=_PROPAGATE_MAX_CHECK_RUNS, check_steps_cap=_PROPAGATE_MAX_CHECK_STEPS)
    return out


# (R60) 출력 관측 MC/DC 쌍 — `generators.observable_mcdc`. 행 이름은 `MCDC_` 로 시작하지 않는다(그 접두는 MC/DC 설계 벡터
#   행만 — finalize · 채움 행 · 기준 순위가 그 이름으로 벡터 행을 찾는다).
OBS_MCDC_PREFIX = "OBS_MCDC_"


def _append_observable_mcdc_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]], ctx: Dict[str, Any]) -> None:
    """(R60, 확장 프로파일) 유지된 MC/DC 쌍의 두 행이 (1) 함수 실행 모델에서 쌍이 주장한 판정을 내고 (2) 쓴 출력에서 갈리는지
    보고, 아니면 — 결정이 의존하는 입력은 쌍의 값 그대로 두고 나머지를 같은 TC 의 다른 행 값으로 바꿔 두 조건을 다 채우는 쌍을
    찾아 행으로 더한다(`find_observable_pairs`). 기존 행 · 쌍은 바꾸지 않는다. 쌍마다 `pair["observable"]`(상태 · 행),
    unit 요약 `unit["observable_mcdc"]`."""
    from generators.observable_mcdc import find_observable_pairs, vector_key
    if not (unit.get("mcdc_design") or {}).get("decisions"):
        unit["observable_mcdc"] = {"status": "no_mcdc_design", "rows": 0}
        return
    var_types = ctx["var_types"]
    domains = _boundary_domains(unit, ctx["input_vars"], var_types, ctx["var_bounds"], set(ctx["unknown"]),
                                ctx.get("enum_sets"))
    outputs = list(dict.fromkeys([*ctx["output_vars"], *(k for s in _search_rows(sequences) for k in (s.get("expected") or {}))]))
    # an existing row a candidate equals becomes that row — only its stated outputs can count (리뷰 R60 2차 W4); the
    #   search and the reuse below use the same key and the same (first) row (3차 W3: 정수 대 서식 JSON 이 갈렸다)
    existing: Dict[tuple, Any] = {}
    stated_of: Dict[tuple, set] = {}
    for s_ in _search_rows(sequences):
        k_ = vector_key(s_.get("inputs") or {})
        if k_ is not None and k_ not in existing:
            existing[k_] = s_.get("seq_num")
            stated_of[k_] = set(s_.get("expected") or {})
    found = find_observable_pairs(unit, sequences, outputs, domains, _base_order(_search_rows(sequences)),
                                  stated_of=stated_of)
    placed: List[Dict[str, Any]] = []
    for row in found["rows"]:
        inputs = {k: _format_test_value(v, var_types.get(k, "uint8_t")) for k, v in row["inputs"].items()}
        key = vector_key(row["inputs"])
        if key in existing:
            row["seq_num"] = existing[key]   # 같은 입력의 행이 이미 있다 — 그 행이 쌍의 구성원이다(근거는 뒤에서 다시 본다)
            continue
        seq = {"seq_num": len(sequences) + 1, "inputs": inputs,
               "expected": {o: f"{VERIFY_PREFIX} observable_mcdc" for o in outputs},
               "strategy": f"{OBS_MCDC_PREFIX}{len(placed)}", "tc_profile": TC_PROFILE_EXTENDED, "description": "",
               "mcdc_observable": {"decision_id": row["decision"]["decision_id"],
                                   "condition_id": row["pair"]["condition_id"], "pair_id": row["pair"]["pair_id"],
                                   "role": row["role"]}}
        sequences.append(seq)
        existing[key] = seq["seq_num"]
        row["seq_num"] = seq["seq_num"]
        placed.append(row)
    by_pair: Dict[int, Dict[str, Any]] = {}
    for row in found["rows"]:
        by_pair.setdefault(id(row["pair"]), {})[row["role"]] = row["seq_num"]
    by_num = {s.get("seq_num"): s for s in sequences}
    for row in placed:
        other = by_pair[id(row["pair"])]["b" if row["role"] == "a" else "a"]
        by_num[row["seq_num"]]["description"] = _observable_row_label(row, other)
    for pair, mark in found["marks"]:
        if mark.get("status") == "searched":
            mark["seq_a"], mark["seq_b"] = by_pair[id(pair)]["a"], by_pair[id(pair)]["b"]
        pair["observable"] = mark
    unit["observable_mcdc"] = {**found["report"], "rows": len(placed)}


def _observable_row_label(row: Dict[str, Any], other: Any) -> str:
    """(R60) 더한 행의 첫 줄 — 무엇을 바꿨고 무엇이 갈리는지, 주장하지 않는 것까지(리뷰 R60 W2: 경로 설계 결정은 결정이 읽는
    입력도 움직일 수 있다 — 쌍의 두 행이 같은 값을 둔 입력만 바꾸고 판정을 함수 실행 모델로 다시 확인한다)."""
    mark = row["mark"]
    changed, moved = mark["outputs_changed"], mark["overlay_inputs"]
    kept = "결정식이 읽지 않는 입력" if mark.get("evaluation") != "source_path" else "쌍의 두 행이 같은 값을 둔 입력"
    return (f"출력 관측 MC/DC 쌍: {row['pair']['pair_id']}({row['role'].upper()}) — {kept}("
            + ", ".join(moved[:3]) + (f" 외 {len(moved) - 3}" if len(moved) > 3 else "")
            + f")을 시퀀스 {row['base']} 의 값으로 두면 두 행이 쌍이 주장한 판정을 내고(함수 실행 모델로 확인) 짝(시퀀스 "
            + f"{other})과, 적어도 한 행의 실행이 쓴 출력("
            + ", ".join(changed[:3]) + (f" 외 {len(changed) - 3}" if len(changed) > 3 else "")
            + ")이 갈린다 (소스 oracle · 미실행 · 그 차이가 이 결정을 거친다는 경로 주장 아님)")


def _confirm_observable_rows(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> None:
    """(R60) 근거를 붙인 뒤 다시 본다 — 탐색으로 찾은 쌍(새 행이든 이미 있던 행이든)의 두 행이, 두 행 모두 적고 둘 다 도출되며
    적어도 한 행의 실행이 쓴(`basis=assigned`) 출력에서 갈리지 않으면 `evidence_mismatch` 로 내리고 새 행의 첫 줄을 고친다
    (리뷰 R60 W6). 탐색과 근거는 같은 oracle 이라 0 이어야 한다."""
    from generators.observable_mcdc import rows_differ
    report = unit.get("observable_mcdc") or {}
    rows = {s.get("seq_num"): s for s in sequences}
    for decision in (unit.get("mcdc_design") or {}).get("decisions") or []:
        for pair in decision.get("pairs") or []:
            mark = pair.get("observable") or {}
            if mark.get("status") != "searched":
                continue
            a, b = rows.get(mark.get("seq_a")), rows.get(mark.get("seq_b"))
            if a is not None and b is not None and rows_differ(a, b):
                for seq in (a, b):
                    if isinstance(seq.get("mcdc_observable"), dict):
                        seq["mcdc_observable"]["confirmed"] = True   # (리뷰 R60 3차 I6)
                continue
            mark["status"] = "evidence_mismatch"
            report["searched"] = max(0, int(report.get("searched") or 0) - 1)
            report["evidence_mismatch"] = int(report.get("evidence_mismatch") or 0) + 1
            for seq in (a, b):
                if seq is not None and str(seq.get("strategy") or "").startswith(OBS_MCDC_PREFIX):
                    if isinstance(seq.get("mcdc_observable"), dict):
                        seq["mcdc_observable"]["confirmed"] = False   # (리뷰 R60 2차 I6)
                    lines = str(seq.get("description") or "").split("\n")
                    lines[0] = (f"출력 관측 MC/DC 쌍 후보 {pair['pair_id']} — 근거를 붙이고 보니 두 행의 쓴 출력이 갈리지 않는다"
                                "(탐색과 근거 불일치 · 쌍 주장 없음)")
                    seq["description"] = "\n".join(lines)


# ── (R19) 소스가 읽는 입력 ──────────────────────────────────────────────────────────────────────────────────────
# oracle 이 기대값을 못 낸 사유 `initial_value_not_in_inputs:X` = 이 행으로 함수를 돌리면 X 를 **쓰기 전에 읽는데** 행이 X 의
# 값을 주지 않았다. 시험 입력 목록(설계서 입력 표·소스 분석)이 그 객체를 빠뜨렸다는 뜻이다. 실측(R17 확장 생성본 · R4 하네스):
# 정본만 판별한 변이 HDPDM01 347 중 244 · KJPDS02_PV 257 중 124 가 이런 함수에 있다 — 예: HDPDM01 SwUDS v1.07 이
# `s_MoveStartClose_GainMeasure` 의 입력으로 **Open** gain 을 적었고 소스는 **Close** gain 을 읽는다(정본 SUTS 는 소스를 따랐다).
# (R39) a struct member (``g.a`` · ``g.s.x`` · ``g.b[2]``) is a name too — the reference sets it by that name
# (백로그 2-c) 쓰지 않은 출력의 최종값 관측에 필요한 초기값(`unwritten_output_initial_not_in_inputs:X`)도 입력으로 더한다 — 그래야
#   그 칸이 도출된다. 다만 함수가 읽은 것이 아니므로 입력 목록 결손 소견(`input_list_gaps`)은 읽은 이름만 센다.
_SOURCE_READ_RE = re.compile("(" + "|".join(re.escape(p[:-1]) for p in (INITIAL_VALUE_PREFIX, UNWRITTEN_OUTPUT_PREFIX))
                             + r"):([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\[\d+\])?)(?![\w.\[])")
# (R81) a pointer parameter's pointee as the reference writes it (`ctx[0].bitcount` · `p[0].b[2]`) — `source_read_names(unit=)`
_POINTEE_READ_RE = re.compile("(" + "|".join(re.escape(p[:-1]) for p in (INITIAL_VALUE_PREFIX, UNWRITTEN_OUTPUT_PREFIX))
                              + r"):([A-Za-z_]\w*\[0\](?:\.[A-Za-z_]\w*)*(?:\[\d+\])?)(?![\w.\[])")
# (R59) 3 → 8: 더한 입력이 연 경로에서 보이는 이름은 분기 깊이만큼 회차가 든다 — 3 회차로는 KJPDS02_PV
#   `s_MotorSpeedModeSelection_RearSet` 의 `u8g_DoorPreCtrl_CompensateLvl`(넷째 분기)이 남아 그 함수의 기대값이 1 칸뿐이었다
#   (실험: 8 회차 34 칸). 새 이름이 없는 회차에서 멈추므로 상한은 그런 함수에만 든다.
_SOURCE_READ_ROUNDS = 8


def source_read_names(sequences: List[Dict[str, Any]], unit: Optional[Dict[str, Any]] = None
                      ) -> Dict[str, Dict[str, Any]]:
    """행이 값을 주지 않았는데 칸이 초기값을 필요로 한 이름 → {"slots": 칸 수, "sequences": [행 번호…], "read": bool}(기대값 근거의
    사유에서). (백로그 2-c) ``read`` 는 한 칸이라도 함수 실행 모델이 그 초기값을 읽어 막혔는지 — 아니면 쓰지 않은 출력의
    최종값(=초기값) 관측에만 필요했다(`UNWRITTEN_OUTPUT_PREFIX`).

    2차원 첨자는 이름으로 싣지 않는다(시험 입력 한 칸으로 줄 수 있는 모양이 아니다). 구조체 멤버 경로(`g.a`)는 R39 부터
    싣는다 — 정본이 `lin_tl_rx_queue.queue_header` 처럼 입력 한 칸으로 쓰고, oracle 이 멤버를 제 이름의 객체로 읽는다.
    (R81) ``unit`` 을 주면 그 함수의 포인터 매개변수 대상(`ctx[0].bitcount` · `p[0].b[2]` — 정본이 입력 한 칸으로 쓰는 표기)도
    싣는다. 주지 않으면 예전 그대로(소견 · 남은 이름은 프로그램 객체만 본다)."""
    scope = (unit or {}).get("project_scope") if isinstance((unit or {}).get("project_scope"), dict) else {}
    out: Dict[str, Dict[str, Any]] = {}
    late: Dict[str, Dict[str, Any]] = {}
    for seq in sequences:
        for ev in (seq.get("expected_evidence") or {}).values():
            for kind, name in _read_names_in(str((ev or {}).get("reason") or ""), unit, scope):
                rec = out.setdefault(name, {"slots": 0, "sequences": [], "read": False})
                rec["slots"] += 1
                # (백로그 2-c) 한 칸이라도 함수 실행 모델이 읽어서 막혔으면 '읽음' — 쓰지 않은 출력의 관측만이면 아님
                rec["read"] = rec["read"] or kind + ":" == INITIAL_VALUE_PREFIX
                if seq.get("seq_num") not in rec["sequences"]:
                    rec["sequences"].append(seq.get("seq_num"))
        if unit is None:
            continue
        # (R81) why an object the run wrote stays unknown (`seq["source_written_unknown"]`) — a counter written from its
        #   own initial value (`s_cnt++`, `ctx->bitcount += n`) is no column yet, so no expected value names that read.
        #   Only a read the model made (not the initial value an unwritten path leaves for the observation — that one is
        #   the next round's, once the object is a column: R80), only of an object the output axis may add, only of one
        #   that is no column yet, and only names no expected value names — with no cells (`slots` 0, as R78's scenario
        #   names): the names the rows already show keep their counts and order (review R81 C1: counted twice, they
        #   reordered the added inputs of units with no pointer at all)
        columns = set(unit.get("output_vars") or ()) | set(seq.get("expected_evidence") or {})
        for obj, reason in (seq.get("source_written_unknown") or {}).items():
            if obj in columns or not str(reason).startswith(INITIAL_VALUE_PREFIX) or not scope \
                    or _unit_object_decl(unit, scope, obj)[1]:
                continue
            for _kind, name in _read_names_in(str(reason), unit, scope):
                rec = late.setdefault(name, {"slots": 0, "sequences": [], "read": True, "written_unknown": 0})
                rec["written_unknown"] += 1
                if seq.get("seq_num") not in rec["sequences"]:
                    rec["sequences"].append(seq.get("seq_num"))
    out.update({n: r for n, r in late.items() if n not in out})
    return out


def _read_names_in(reason: str, unit: Optional[Dict[str, Any]], scope: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(kind, name) a reason names — program objects (`_SOURCE_READ_RE`) and, with ``unit``, its pointer parameters'
    pointees (`_POINTEE_READ_RE`, R81)."""
    found = _SOURCE_READ_RE.findall(reason)
    if unit is not None and "[0]" in reason:
        seen = {n for _k, n in found}
        found += [(k, n) for k, n in _POINTEE_READ_RE.findall(reason)
                  if n not in seen and _pointee_object_decl(unit, scope, n) is not None]
    return found


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


def _pointee_object_decl(unit: Dict[str, Any], scope: Dict[str, Any], name: str
                         ) -> Optional[Tuple[Optional[str], str]]:
    """(R81) 이 unit 함수의 포인터 매개변수가 가리키는 대상(`p[0]` · `p[0].a` · `p[0].b[2]` — 정본 표기)이면 (선언 타입 이름, "")
    또는 (None, 더하지 않는 사유), 그 매개변수의 대상 표기가 아니면 None. 타입은 소스의 대상 배치(R40 `_pointee_input`) —
    대상 멤버를 모델이 모르면 `pointee_member_unmodeled`, volatile · 부동소수는 프로그램 객체와 같은 사유."""
    from generators.mcdc_design import _POINTEE_INPUT_RE, _pointee_input, _pointer_params
    # (R82) or `p[k]` — an element of a scalar pointee the harness holds as a buffer (`pData[1]`)
    m = _POINTEE_INPUT_RE.fullmatch(str(name).strip()) or re.fullmatch(r"([A-Za-z_]\w*)\[(\d+)\]", str(name).strip())
    fn = str(unit.get("name") or "")
    if not m or not scope or m.group(1) not in _pointer_params(scope, fn):
        return None
    found = _pointee_input(scope, fn, name)
    if found is None:
        return None, "pointee_member_unmodeled"
    t, typename, volatile = found
    if volatile:
        return None, "volatile_object"
    from generators.c_project_context import is_float
    if is_float(t):
        return None, "float_object"
    typename = str(typename or "").strip()
    return (typename, "") if typename else (None, "no_declared_type")


def _unit_object_decl(unit: Dict[str, Any], scope: Dict[str, Any], name: str) -> Tuple[Optional[str], str]:
    """(R81) 입력 · 출력 보완이 더할 수 있는 객체 — 번역 단위의 프로그램 객체(`_source_object_decl`)와 이 unit 함수의 포인터
    매개변수 대상(`_pointee_object_decl`). KJPDS02_PV 설계서는 출력 전용 매개변수를 포인터 이름으로만 적었다(`s_sha256_init`
    의 `ctx`, `s_ApplyTemperatureCompensation` 의 `u16p_Peak`) — 정본은 `ctx[0].state[1]` · `u16p_Peak[0]` 을 관측했다."""
    pointee = _pointee_object_decl(unit, scope, name)
    return pointee if pointee is not None else _source_object_decl(scope, name)


#: (R82) elements of one pointer parameter's buffer (`pData[k]`, `RespMsg[0].data[k]`) the completion adds as columns — a loop that
#   clears a buffer writes every element it reaches (`g_Lib_u8bit_ArrayClear`: 84 output and 86 input columns, 255 rows)
_BUFFER_ELEMENTS_MAX = 8   # a LIN frame, a UDS response: 8 bytes (KJPDS02_PV `RespMsg[0].data[4]` and `[5]`)


_HARNESS_ELEMENT_RE = re.compile(r"([A-Za-z_]\w*)((?:\[0\](?:\.[A-Za-z_]\w*)+)?)\[(\d+)\]")


def _harness_buffer_base(unit: Dict[str, Any], scope: Dict[str, Any], name: str) -> Optional[Tuple[str, int]]:
    """(R82, review C2) ``(buffer, index)`` when ``name`` is an element of a harness buffer — ``p[k]`` of a pointer parameter
    whose pointee is a scalar, ``p[0].m[k]`` of a one-level pointer member of its pointee (`pointee_types[…]["pointers"]`)
    — else None: a fixed-length member array ``p[0].b[k]`` (R40/R81 — `ctx[0].data[63]`) is no harness buffer."""
    m = _HARNESS_ELEMENT_RE.fullmatch(str(name).strip())
    if not m or not scope:
        return None
    from generators.mcdc_design import _pointee_core, _pointer_params
    params = _pointer_params(scope, str(unit.get("name") or ""))
    if m.group(1) not in params:
        return None
    layout = ((scope.get("pointee_types") or {}).get(_pointee_core(params[m.group(1)]))) or {}
    if not m.group(2):
        scalar = set(layout.get("members") or {}) == {""} and not layout.get("arrays")
        return (m.group(1), int(m.group(3))) if scalar else None
    path = m.group(2)[len("[0]"):]
    return (m.group(1) + m.group(2), int(m.group(3))) if path in (layout.get("pointers") or {}) else None


def _column_order(unit: Dict[str, Any], scope: Dict[str, Any], name: str) -> Tuple[str, int]:
    """(R82) A candidate's tie-break: its name — a harness buffer element by its buffer and index (`p[2]` before `p[10]`,
    so the cap keeps the first elements)."""
    found = _harness_buffer_base(unit, scope, name)
    return found if found is not None else (name, -1)


def _buffer_elements_full(unit: Dict[str, Any], scope: Dict[str, Any], name: str, columns: List[str]) -> bool:
    """(R82) Whether ``name`` is an element of a harness buffer (`_harness_buffer_base`) whose `_BUFFER_ELEMENTS_MAX`
    elements already are columns."""
    found = _harness_buffer_base(unit, scope, name)
    if found is None:
        return False
    return sum(1 for c in columns if c != name and (_harness_buffer_base(unit, scope, c) or ("",))[0] == found[0]
               ) >= _BUFFER_ELEMENTS_MAX


def _unit_input_types(unit: Dict[str, Any], names: List[str]
                      ) -> Tuple[Dict[str, str], Dict[str, Dict[str, Any]], Dict[str, str]]:
    """(R81) `scope_input_types` 에 포인터 매개변수 대상을 더한 것 — 대상은 R40 `pointee_input_types`(소스 대상 배치)."""
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    pointee = [n for n in names if _pointee_object_decl(unit, scope, n) is not None]
    types, domains, reasons = scope_input_types(unit, [n for n in names if n not in pointee])
    if pointee:
        ptypes, pdomains = pointee_input_types(unit, pointee)
        types.update(ptypes)
        domains.update(pdomains)
        reasons.update({n: "type_not_resolved" for n in pointee if n not in ptypes and n not in pdomains})
    return types, domains, reasons


def pointee_input_types(unit: Dict[str, Any], names: List[str]
                        ) -> Tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    """(R40) 포인터 매개변수가 가리키는 대상 입력(`p[0]` · `p[0].a` · `p[0].b[2]`)의 (경계값 표의 타입 키, enum 값 집합) —
    소스의 함수 정의(`project_scope.pointer_params`)와 대상 배치(`pointee_types`)에서. 설계서 문자열이 아니라 소스가 정한다.
    키는 `scope_input_types` 처럼 **해석된** 타입의 폭·부호로 정한다(리뷰 R40 W5: 표가 모르는 typedef 이름 `tU8` 을 그대로
    넘기면 타입 미상이 돼 칸이 빈다). enum 은 그 번역 단위의 열거자 값 집합. 모르면 싣지 않는다."""
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    types: Dict[str, str] = {}
    domains: Dict[str, Dict[str, Any]] = {}
    if not scope:
        return types, domains
    from generators import c_project_context as cpc
    from generators.mcdc_design import _pointee_input, _scope_domain
    for v in names:
        found = _pointee_input(scope, str(unit.get("name") or ""), v)
        if found is None:
            continue
        t, typename, _volatile = found
        if cpc.is_float(t):
            continue
        if t.get("enum"):
            try:
                dom = _scope_domain(t, typename, scope, "enum_declaration")
            except (cpc.Unresolved, KeyError, TypeError):
                continue
            domains[v] = {"values": list(dom["values"]), "source": "pointee_declaration"}
            continue
        key = "bool" if t.get("kind") == "_Bool" else _SCOPE_TYPE_KEYS.get((t.get("bits"), bool(t.get("signed"))), "")
        if key:
            types[v] = key
    return types, domains


def complete_source_read_inputs(unit: Dict[str, Any], sequences: List[Dict[str, Any]],
                                regenerate: Callable[[], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """(R19, 확장 프로파일) 소스가 읽는데 입력 목록에 없는 프로그램 객체를 **선언 타입으로** 입력 열에 더하고 다시 만든다.

    회차마다 `source_read_names` 가 찾은 이름 중 번역 단위의 스칼라 객체(또는 1차원 배열 원소)만 더한다. 더한 입력은 기본 카탈로그
    행에선 고정값이고(구조는 `unit["design_input_vars"]` = 설계 입력 목록으로 정해진다 — `generate_sequences`), OAT·경계 행에서
    선언 타입(enum 은 그 번역 단위의 열거자) 범위를 움직인다. 더한 입력이 새 경로를 열어 또 다른 이름이 보이면 다음 회차(최대
    `_SOURCE_READ_ROUNDS`)에서 더한다. `regenerate()` 는 경계 행 없이 다시 만든다 — 경계 행은 호출자가 마지막에 한 번 붙인다.
    입출력이 없는 unit(전략 목록 대신 호출 시퀀스를 쓰는 경로)은 건드리지 않는다. 기록은 `unit["source_read_inputs"]`:
    더한 이름(처음 본 칸 수·회차·타입 · 함수 실행 모델이 읽었는지 `read_on_model` — 백로그 2-c) · 더하지 않은 이름과 사유 ·
    마지막 행들에서도 값이 없는 이름(`remaining`)."""
    record: Dict[str, Any] = {"added": {}, "not_added": {}, "rounds": 0, "remaining": {}}
    # (review R82 W8) a write's prior value the completion did not add, and why — apart from the names the source reads
    #   (`not_added` · the input column cap the disclosure warns about are theirs)
    prior_not_added: Dict[str, str] = {}
    last_unobserved: Dict[str, str] = {}   # (review R82 W-R4-1) of the last round whose prior pass ran
    unit["source_read_inputs"] = record
    # (R80) 소스가 쓰는 출력 — 같은 회차에 더한다(더한 출력을 쓰지 않는 경로의 최종값은 초기값이라 다음 회차의 입력이 된다 —
    #   백로그 2-c 사유 `unwritten_output_initial_not_in_inputs`)
    written = _new_written_record()
    unit["source_written_outputs"] = written
    if not (unit.get("input_vars") or unit.get("output_vars")):
        record["not_added"] = {n: "unit_without_inputs_or_outputs" for n in source_read_names(sequences)}
        written["not_added"] = {n: "unit_without_inputs_or_outputs" for n in source_written_names(sequences)}
        return sequences
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    max_inp = _INPUT_COL_END - _INPUT_COL_START + 1
    for _round in range(_SOURCE_READ_ROUNDS):
        new_out: List[str] = []
        if not written.get("error"):
            try:
                new_out = _add_written_outputs(unit, _search_rows(sequences), written, _round + 1)
            except Exception as exc:  # noqa: BLE001 — (review R80 I2) the output axis alone stops; the inputs go on
                _logger.warning("SUTS 소스가 쓰는 출력 실패(%s): %s", unit.get("name"), exc, exc_info=True)
                written["error"] = type(exc).__name__
        # (R81) pointees too. A name the rows also read stays the rows' (R78 — `scenario_targets` marks the names only the
        #   scenario search needed: `names_added_by_scenario_search`; review R81 I-R2-5 reverted for that reason)
        found = {**_scenario_needed_names(unit), **source_read_names(_search_rows(sequences), unit)}
        inputs = list(unit.get("input_vars") or [])
        new: List[str] = []
        ordered = sorted(found.items(), key=lambda kv: (-kv[1]["slots"], _column_order(unit, scope, kv[0])))
        # (R82, review R82 W5) a write's prior value only (`prior_value_for_write` — read by no row and no search) waits
        #   for a round that adds no name the source reads: a column it took would be one a later round's read lacks
        reads = [(n, r) for n, r in ordered if not _prior_only(r)]
        unobserved: Dict[str, str] = {}   # (review R82 I-R3-1) this round's verdict — a later round's R80 may add the column
        for pass_ in ("read", "prior"):
            candidates = reads if pass_ == "read" else [(n, r) for n, r in ordered if _prior_only(r)]
            if pass_ == "prior" and new:
                break
            if pass_ == "prior":
                last_unobserved = unobserved
            for name, rec in candidates:
                book = record["not_added"] if pass_ == "read" else prior_not_added
                if name in inputs or name in record["added"] or name in book:
                    continue   # 열은 있는데 그 행이 비운 칸(MC/DC 벡터) — 채움 행의 몫
                if pass_ == "prior" and name not in (unit.get("output_vars") or []):
                    unobserved[name] = "not_observed"   # (review R82 I-R2-1) no expected column sees the write's deletion
                    continue
                typename, why = _unit_object_decl(unit, scope, name) if scope else (None, "no_project_scope")
                if not why:
                    key, enum, reasons = _unit_input_types(unit, [name])
                    why = reasons.get(name, "")
                if not why and _buffer_elements_full(unit, scope, name, inputs + new):
                    why = "buffer_elements_full"
                if not why and len(inputs) + len(new) >= max_inp:
                    why = "input_columns_full"
                if why:
                    book[name] = why
                    continue
                new.append(name)
                _record_added_input(unit, record, name, rec, _round + 1, typename, key, enum)
        if not new and not new_out:
            break
        if new:
            unit.setdefault("design_input_vars", list(inputs))
            unit["input_vars"] = inputs + new
            record["rounds"] = _round + 1
        if new_out:
            written["rounds"] = _round + 1
        sequences = regenerate()
    else:
        # (R59) 상한 회차까지 이름을 더했다 — 상한이 탐색을 **잘랐는지**는 마지막 행들을 한 번 더 보고(다시 만들지 않고)
        #   다음 회차가 더했을 이름이 있는지로 가린다(리뷰 R59 W1: 필요한 회차가 정확히 상한이면 자른 것이 아니다)
        inputs = set(unit.get("input_vars") or [])
        beyond, prior_beyond = [], []
        for name, rec in {**_scenario_needed_names(unit), **source_read_names(_search_rows(sequences), unit)}.items():
            if name in inputs or name in record["added"] or name in record["not_added"] or name in prior_not_added:
                continue
            typename, why = _unit_object_decl(unit, scope, name) if scope else (None, "no_project_scope")
            if not why:
                why = _unit_input_types(unit, [name])[2].get(name, "")
            if not why and _prior_only(rec) and name not in (unit.get("output_vars") or []):
                last_unobserved[name] = "not_observed"   # (review R82 I-R4-1) unobserved — not a name the cap left
            elif not why:
                (prior_beyond if _prior_only(rec) else beyond).append(name)
        record["round_cap_reached"] = bool(beyond or prior_beyond)
        record["names_beyond_cap"] = beyond
        if prior_beyond:
            # (review R82 W5) prior values wait for the reads: at the cap they are left — no row reads them
            record["prior_values_beyond_cap"] = prior_beyond
        # (R80) 출력 축도 같은 질문 — 다음 회차가 더했을 이름(기록은 바꾸지 않는다; 남은 것은 마지막 보완이 더한다)
        try:
            written["round_cap_reached"] = (not written.get("error")
                                            and bool(_written_output_candidates(unit, _search_rows(sequences), written)[0]))
        except Exception as exc:  # noqa: BLE001 — (review R80 I-R2-7) the output axis alone, as in the rounds
            _logger.warning("SUTS 소스가 쓰는 출력 실패(%s): %s", unit.get("name"), exc, exc_info=True)
            written["error"] = type(exc).__name__
    # (review R82 W-R4-1) once, at the end: a name a later round added is no longer 'not added'
    left = {n: why for n, why in {**last_unobserved, **prior_not_added}.items() if n not in record["added"]}
    if left:
        record["prior_value_not_added"] = left
    _record_remaining(unit, sequences)
    return sequences


def _prior_input_names(unit: Dict[str, Any]) -> set:
    """(R82) Inputs the completion added only as a write's prior value (no row and no search reads them)."""
    return {n for n, a in (((unit.get("source_read_inputs") or {}).get("added")) or {}).items()
            if isinstance(a, dict) and a.get("prior_value_for_write") and not a.get("read_on_model", True)}


def _prior_fill_overrides(unit: Dict[str, Any], fill: Dict[str, int], domains: Dict[str, Any],
                          var_bounds: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, int], List[str]]:
    """(R82) A write's prior value only: the value a row leaves it at (``fill``, the blank-fill rule) must differ from every
    value the function writes there, else the rows keeping it fixed — most of them, when the exposing search runs out of
    budget — cannot tell the write's deletion (PV `g_UDS_LinComp_Reset`: `u8g_SysUds_UsDoorCtrl = u8g_CLR` over a fixed 0).
    The new value lies in the input's domain: a range keeps ``lo..hi`` (its mid first), a value set — an enum's
    enumerators, a design value list — keeps one of its values (review R82 W-R5-1: the midpoint 1 of a design range 0~3
    is no enumerator of {0, 2, 3}). Returns the moved values and the names whose every candidate is written (left as
    they were — the rows cannot tell that write's deletion)."""
    moved: Dict[str, int] = {}
    collide: List[str] = []
    for v in sorted(_prior_input_names(unit)):
        rec = unit["source_read_inputs"]["added"][v]
        written = {x for x in rec.get("written_values") or () if isinstance(x, int) and not isinstance(x, bool)}
        if v not in fill or fill[v] not in written:
            continue
        dom = domains.get(v)
        mid = (var_bounds.get(v) or {}).get("mid")
        mid = mid if isinstance(mid, int) and not isinstance(mid, bool) else None
        if isinstance(dom, tuple) and len(dom) == 2:
            lo, hi = dom
            cands = [x for x in (mid, (lo + hi) // 2, (lo + hi) // 2 + 1, lo + 1, hi, lo)
                     if x is not None and lo <= x <= hi]
        elif isinstance(dom, (list, set, frozenset)):
            values = sorted(dom)
            cands = ([mid] if mid in values else []) + values
        else:
            cands = []
        pick = next((x for x in cands if x not in written), None)
        if pick is None:
            collide.append(v)
        else:
            moved[v] = pick
    return moved, collide


def _prior_only(rec: Dict[str, Any]) -> bool:
    """(R82) A name found only as a write's prior value: no row and no search reads it (`_scenario_needed_names`)."""
    return bool(rec.get("prior_value_for_write")) and not rec.get("read", True)


def _record_added_input(unit: Dict[str, Any], record: Dict[str, Any], name: str, rec: Dict[str, Any], round_: int,
                        typename: Any, key: Dict[str, str], enum: Dict[str, Any]) -> None:
    """(R19) The completion's record of an input it added, and its type in the unit (`complete_source_read_inputs`)."""
    record["added"][name] = {"slots": rec["slots"], "round": round_, "type": typename,
                             "value_type": key.get(name) or "enum",
                             # (백로그 2-c) 함수 실행 모델이 읽어서 막혔는지, 쓰지 않은 출력의 최종값을 보려고인지 —
                             #   False 는 '모델에서 읽힌 근거 없음'(쓰기 요약만 있는 callee 안의 읽기는 모델에 없다)
                             "read_on_model": bool(rec.get("read", True))}
    if rec.get("scenario_targets"):
        # (R78) 행이 아니라 동작 시나리오 탐색이 그 경로에 닿으려다 읽은 이름 — 처음 본 칸은 없다(행이 아직 없다)
        record["added"][name]["scenario_targets"] = rec["scenario_targets"]
    if rec.get("prior_value_for_write"):
        # (R82) 탐색이 노출하지 못한 쓰기(그 객체의 이전 값을 모른다)의 수 — 행이 쓰기 전 값을 정해야 쓰기 삭제가 드러난다.
        #   함수가 거기 쓰는 값(`written_values`) — 행의 고정값은 그와 달라야 삭제가 보인다(`generate_sequences`)
        record["added"][name]["prior_value_for_write"] = rec["prior_value_for_write"]
        if rec.get("written_values"):
            record["added"][name]["written_values"] = list(rec["written_values"])
    if name in key:
        unit["source_input_types"] = {**(unit.get("source_input_types") or {}), name: key[name]}
    else:
        # (리뷰 R1 I5) 그 번역 단위의 열거자 — 전역 표는 이름으로 묶여 같은 이름의 다른 static 것일 수 있다.
        #   덮기 전 값 집합은 카탈로그 구조 판정용으로 남긴다(리뷰 R3 W1: GLOBAL 행이 기본 영역에서 사라졌다).
        prev = (unit.get("value_domains") or {}).get(name)
        if prev:
            unit["design_value_domains"] = {**(unit.get("design_value_domains") or {}), name: prev}
        unit["value_domains"] = {**(unit.get("value_domains") or {}), name: enum[name]}


def _scenario_needed_names(unit: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """(R78) 동작 시나리오 탐색이 깨끗하게 닿지 못한 문장 · 분기에 가는 실행이 값 없이 읽은 프로그램 객체 — `source_read_names` 와
    같은 모양(행이 없어 칸 수 0)에 그 이름이 막은 목표 수(`scenario_targets`). 행의 근거만 보면 어떤 행도 닿지 않은 경로가 읽는
    이름은 영영 안 보인다(HDPDM01 `s_MoveStartClose_GainMeasure` 의 뒷문 Close 이득 — SwUDS 입력 표는 Open 이득을 적었다)."""
    rep = unit.get("scenario_rows") if isinstance(unit.get("scenario_rows"), dict) else {}
    # (R82) 쓰기 전 값 — 탐색이 노출하지 못한 쓰기가 덮는 값을 알 수 없는 객체(입력이 아님). 함수는 거기서 그 객체를 쓰지 읽지 않는다:
    #   모델에서 읽힌 근거가 아니고(`read` False — 입력 목록 결손 소견 아님) 읽힌 이름보다 뒤에 선다(열 상한). 탐색이 번역 단위
    #   객체와 포인터 매개변수 대상만 청한다(`scenario_rows` — 초기화하지 않은 지역은 시험이 정할 객체가 아니다)
    written = rep.get("prior_value_written") if isinstance(rep.get("prior_value_written"), dict) else {}
    out = {n: {"slots": 0, "sequences": [], "read": False, "prior_value_for_write": int(k),
               "written_values": list(written.get(n) or [])}
           for n, k in (rep.get("prior_value_needed") or {}).items()}
    for n, k in (rep.get("needed_inputs") or {}).items():
        out[n] = {**out.get(n, {}), "slots": 0, "sequences": [], "read": True, "scenario_targets": int(k)}
    return out


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
    # (review R80 W7) a column the last written-output pass added needs its initial value only to observe the paths that
    #   leave it unwritten — counted there (`final_initial_not_in_inputs`), not as a name the rows read
    late = {n for n, a in (((unit.get("source_written_outputs") or {}).get("added")) or {}).items()
            if (a or {}).get("round") == "final"}
    record["remaining"] = {n: r["slots"] for n, r in final.items() if n not in now and n.partition("[")[0] in objects
                           and not (n in late and not r.get("read"))}
    for n, added in (record.get("added") or {}).items():
        if not any(n in (q.get("inputs") or {}) for q in sequences):
            record["remaining"][n] = final.get(n, {}).get("slots", 0)
            added["no_value_in_any_row"] = True


# ── (R80) 소스가 쓰는 출력 ───────────────────────────────────────────────────────────────────────────────────────────
# 백로그 2-b(R59 에서 뺀 것)를 함수 실행 모델 위에서 다시 한다: 행의 실행이 실제로 쓴 번역 단위 객체(`apply_sequence_evidence(
# written=True)` → `seq["source_written"]`) 중 시험 기대 목록에 없는 것. R59 초안은 본문을 걸어 대입을 셌고 비활성 `#if` 팔 ·
# 버려지는 매크로 인자 안의 대입까지 셌다(리뷰 W1) — 실행 모델은 그 빌드에서 그 경로가 실제로 저장한 객체만 남긴다. 실측(HDPDM01,
# R79 정본만 판별한 변이): `u8s_SbcmMsg2_LinTmOutCheck` 는 `u8s_SbcmMsg2LinFailTimer` · `u16s_SbcmMsg2LinFailTm` 을 쓰는데
# SwUDS 출력 표는 형제 함수의 `u8s_SbcmMsgLinFailTimer` · `u16s_SbcmMsgLinFailTm` 을 적었다 — 생성 SUTS 는 함수가 쓰지 않는
# 변수만 관측해 그 함수의 쓰기 삭제 변이 둘을 정본만 판별했다.
SOURCE_WRITTEN_PLACEHOLDER = "source_written_output"


def _new_written_record() -> Dict[str, Any]:
    return {"added": {}, "not_added": {}, "dropped": {}, "rounds": 0, "never_known": []}


def source_written_names(sequences: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """(R80) 행의 실행이 쓴 프로그램 객체 → {"rows": 쓴 행 수, "known": 그 뒤 값이 하나로 도출된 행 수, "sequences": [행 번호…]}
    (`seq["source_written"]` — `apply_sequence_evidence(written=True)` 가 단다)."""
    out: Dict[str, Dict[str, Any]] = {}
    for seq in sequences:
        for name, known in (seq.get("source_written") or {}).items():
            rec = out.setdefault(name, {"rows": 0, "known": 0, "sequences": []})
            rec["rows"] += 1
            rec["known"] += 1 if known else 0
            if seq.get("seq_num") not in rec["sequences"]:
                rec["sequences"].append(seq.get("seq_num"))
    return out


def _written_output_candidates(unit: Dict[str, Any], sequences: List[Dict[str, Any]], record: Dict[str, Any]
                               ) -> Tuple[List[str], Dict[str, str]]:
    """(R80) (더할 이름, 더하지 않는 이름 → 사유) — 기록은 바꾸지 않는다. 후보: 출력 목록 밖에서 어느 행의 실행이 쓰고 그 뒤 값이
    도출된 객체(한 번도 값이 서지 않는 열은 빈칸만 는다 — 다음 회차에 서면 그때), 입력 보완과 같은 규칙(`_source_object_decl` —
    번역 단위의 스칼라 · 길이 안 1차원 원소, const · volatile · 부동소수 · 선언 타입 없음 제외), 기대값 열 상한 안(R59 W4).
    값이 선 행이 많은 이름부터."""
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    outputs = set(unit.get("output_vars") or [])
    room = _OUTPUT_COL_END - _OUTPUT_COL_START + 1 - len(outputs)
    seen = set(record["added"]) | set(record["not_added"]) | set(record["dropped"])
    new: List[str] = []
    skipped: Dict[str, str] = {}
    for name, rec in sorted(source_written_names(sequences).items(),
                            key=lambda kv: (-kv[1]["known"], -kv[1]["rows"], _column_order(unit, scope, kv[0]))):
        if name in outputs or name in seen or not rec["known"]:
            continue
        _typename, why = _unit_object_decl(unit, scope, name) if scope else (None, "no_project_scope")
        if not why and _buffer_elements_full(unit, scope, name, list(outputs) + new):
            why = "buffer_elements_full"
        if not why and len(new) >= room:
            why = "output_columns_full"
        if why:
            skipped[name] = why
        else:
            new.append(name)
    return new, skipped


def _add_written_outputs(unit: Dict[str, Any], sequences: List[Dict[str, Any]], record: Dict[str, Any],
                         round_label: Any) -> List[str]:
    """(R80) 후보를 출력 목록 뒤에 더하고(설계 목록은 `design_output_vars` 에 한 번 남긴다) 기록한다 — 더한 이름."""
    new, skipped = _written_output_candidates(unit, sequences, record)
    record["not_added"].update(skipped)
    if not new:
        return []
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    counts = source_written_names(sequences)
    for name in new:
        record["added"][name] = {"rows": counts[name]["rows"], "rows_known": counts[name]["known"], "round": round_label,
                                 "type": _unit_object_decl(unit, scope, name)[0]}
    unit.setdefault("design_output_vars", list(unit.get("output_vars") or []))
    unit["output_vars"] = list(unit.get("output_vars") or []) + new
    return new


def _rewrite_expected_line(seq: Dict[str, Any]) -> None:
    """설명의 `Expected:` · `근거: 소스 계산` 줄을 지금의 기대값으로 다시 쓴다(`render_row_io` 와 같은 규칙)."""
    desc = [ln for ln in str(seq.get("description") or "").splitlines() if not ln.startswith(("Expected:", "근거: 소스 계산"))]
    if seq.get("expected"):
        desc.append("Expected: " + ", ".join(f"{v}={x}" for v, x in seq["expected"].items()))
    if any((e or {}).get("status") == "derived" for e in (seq.get("expected_evidence") or {}).values()):
        desc.append("근거: 소스 계산 (요구 적합성 미검증, 실행 미실시)")
    seq["description"] = "\n".join(desc)


def _drop_underived_written_outputs(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> List[str]:
    """(R80) 더한 출력 중 어느 행도 값을 내지 못한 이름은 다시 뺀다(출력 목록 · 행의 기대값 · 근거 · 설명에서). 그 이름의 쓰지
    않은 경로 초기값으로 입력 보완이 더한 입력(모델에서 읽힌 근거 없이 더한 것)은 남는다 — `input_kept` 로 센다(R59 W3)."""
    record = unit.get("source_written_outputs") or {}
    added = record.get("added") or {}
    derived = {n for s in sequences for n, ev in (s.get("expected_evidence") or {}).items()
               if n in added and (ev or {}).get("status") == "derived"}
    drop = [n for n in added if n not in derived]
    if not drop:
        return []
    inputs_added = (unit.get("source_read_inputs") or {}).get("added") or {}
    for seq in sequences:
        if any(n in (seq.get("expected") or {}) or n in (seq.get("expected_evidence") or {}) for n in drop):
            for n in drop:
                (seq.get("expected") or {}).pop(n, None)
                (seq.get("expected_evidence") or {}).pop(n, None)
            _rewrite_expected_line(seq)
    for n in drop:
        rec = added.pop(n)
        rec["input_kept"] = n in inputs_added and not (inputs_added[n] or {}).get("read_on_model", True)
        record["dropped"][n] = rec
    unit["output_vars"] = [v for v in unit.get("output_vars") or [] if v not in drop]
    return drop


def complete_source_written_outputs(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """(R80, 확장 프로파일) 회차가 끝난 뒤 붙은 행(경계 · 강건성 · 출력 관측 쌍 · 설계 범위 밖 시나리오)의 실행이 쓴 객체까지 —
    남은 후보를 더하고 모든 행의 근거를 다시 붙인다(새 열의 값; 기존 칸은 같은 입력 · 같은 oracle 이라 그대로). 그 뒤 어느
    행도 값을 내지 못한 더한 이름은 뺀다. 값이 한 번도 서지 않아 더하지 않은 이름은 `never_known` 으로 센다."""
    record = unit.get("source_written_outputs")
    if not isinstance(record, dict) or "added" not in record:
        return sequences
    # (review R80 W1 · W-R2-4) rows whose written record failed — counted even when the axis stopped
    record["rows_written_error"] = sum(1 for s in sequences if s.get("source_written_error"))
    before = list(unit.get("output_vars") or [])
    had_design = "design_output_vars" in unit
    try:
        # (review R80 I-R2-8) after an error in the rounds: add nothing, but drop what no row derives and count
        late = [] if record.get("error") else _add_written_outputs(unit, _search_rows(sequences), record, "final")
        prior = (unit.get("source_read_inputs") or {}).get("prior_value_not_added")
        for n in late if isinstance(prior, dict) else ():
            if prior.get(n) == "not_observed":
                prior[n] = "observed_only_in_final"   # (review R82 I-R3-1) a column now — no round is left to add its prior
        if late:
            # (review R80 W7) a slot in every row, as the round-added columns have — a row the oracle derives nothing for
            #   says why (`[검증 필요] <reason>`) instead of a blank
            for seq in sequences:
                exp = seq.setdefault("expected", {})
                for n in late:
                    exp.setdefault(n, f"{VERIFY_PREFIX} {SOURCE_WRITTEN_PLACEHOLDER}")
            sequences = apply_sequence_evidence(unit, sequences, written=True)
            # the paths that leave a late column unwritten need its initial value — no round is left to add it as an
            #   input: counted here (not as a source-read name left over — review R80 W7)
            record["final_initial_not_in_inputs"] = sorted(n for n in late if any(
                str((ev or {}).get("reason") or "").startswith(UNWRITTEN_OUTPUT_PREFIX)
                for s in sequences for k, ev in (s.get("expected_evidence") or {}).items() if k == n))
        dropped = _drop_underived_written_outputs(unit, sequences)
        scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
        for _again in range(2):
            if not any(_pointee_object_decl(unit, scope, n) is not None for n in dropped):
                break
            # (R81, review I5 · I-R2-1) an observed pointee column set its parameter's pointee up for every row: gone,
            #   the rows run again as the document now observes them — no value may rest on a harness object no column
            #   names; a run that drops another parameter's pointee column runs once more
            sequences = apply_sequence_evidence(unit, sequences, written=True)
            dropped = _drop_underived_written_outputs(unit, sequences)
            # (review R81 I-R3-3) the counts of the rows as they now stand
            record["rows_written_error"] = sum(1 for s in sequences if s.get("source_written_error"))
            if "final_initial_not_in_inputs" in record:
                record["final_initial_not_in_inputs"] = sorted(n for n in record["final_initial_not_in_inputs"] if any(
                    str((ev or {}).get("reason") or "").startswith(UNWRITTEN_OUTPUT_PREFIX)
                    for s in sequences for k, ev in (s.get("expected_evidence") or {}).items() if k == n))
        else:
            record["pointee_rerun_cap_reached"] = any(_pointee_object_decl(unit, scope, n) is not None for n in dropped)
    except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
        _logger.warning("SUTS 소스가 쓰는 출력 마지막 보완 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        # (review R80 I3) take back what this pass added — by name, not by the list before it (a drop may have run)
        late = [n for n in unit.get("output_vars") or [] if n not in before] + \
            [n for n, a in list(record["added"].items()) if a.get("round") == "final"]
        late = list(dict.fromkeys(late))
        unit["output_vars"] = [v for v in unit.get("output_vars") or [] if v not in late]
        if not had_design and not record["added"].keys() - set(late):
            unit.pop("design_output_vars", None)
        for n in late:
            record["added"].pop(n, None)
            record["dropped"].pop(n, None)
        record.pop("final_initial_not_in_inputs", None)
        for seq in sequences:
            if any(n in (seq.get("expected") or {}) or n in (seq.get("expected_evidence") or {}) for n in late):
                for n in late:
                    (seq.get("expected") or {}).pop(n, None)
                    (seq.get("expected_evidence") or {}).pop(n, None)
                _rewrite_expected_line(seq)
        record["final_error"] = type(exc).__name__
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    outputs = set(unit.get("output_vars") or [])
    # (review R82 I-R3-2) a harness buffer element written past what the row names is past the allocation — no object
    #   whose value never settled: counted apart (a clearing loop wrote 254 of them)
    #   — the buffer's own elements: the objects that write may have reached carry the same reason (review R82 W-R4-2)
    past = {n for s in sequences for n, why in (s.get("source_written_unknown") or {}).items()
            if str(why).startswith("harness_buffer_write_beyond_row:")
            and _harness_element_of(n, str(why).split(":", 1)[1])}
    record["never_known"] = sorted(n for n, r in source_written_names(sequences).items()
                                   if not r["known"] and n not in outputs and n not in record["not_added"]
                                   and n not in past and scope and not _unit_object_decl(unit, scope, n)[1])
    if past - outputs:
        record["written_past_allocation"] = sorted(past - outputs)
    prior = (unit.get("source_read_inputs") or {}).get("prior_value_not_added")
    for n, why in list((prior if isinstance(prior, dict) else {}).items()):
        if why == "observed_only_in_final" and n not in outputs:
            prior[n] = "not_observed"   # (review R82 I-R4-2) the late column was dropped again
    return sequences


def _harness_element_of(name: str, buffer: str) -> bool:
    """(review R82 W-R4-2) Whether ``name`` is ``buffer[k]``."""
    return name.startswith(buffer + "[") and name.endswith("]") and name[len(buffer) + 1:-1].isdigit()


def _design_outputs(unit: Dict[str, Any]) -> List[str]:
    """(R80) 시험 기대 목록의 설계 쪽 — 확장이 더하기 전 목록(`design_output_vars`), 없으면 출력 목록에서 행이 적어 열로 보인
    이름(R21 `render_row_io`)을 뺀 것."""
    if unit.get("design_output_vars") is not None:
        return list(unit["design_output_vars"])
    shown = set(((unit.get("row_io_columns") or {}).get("outputs_shown")) or [])
    return [v for v in unit.get("output_vars") or [] if v not in shown]


def _containers(name: str) -> List[str]:
    """The objects ``name`` is part of — ``g.s.a[2]`` → ``g``, ``g.s``, ``g.s.a``; ``g.a[1].b`` → ``g``, ``g.a``,
    ``g.a[1]`` (review R80 W6 · I-R2-6)."""
    steps = re.findall(r"\.?[A-Za-z_]\w*|\[\d+\]", name)
    return ["".join(steps[:i]) for i in range(1, len(steps))]


# (review R80 I8) written objects a finding names though no column can take them (no expected value: volatile, float)
_FINDING_ONLY = frozenset({"volatile_object", "float_object"})


def output_list_gaps(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """(R80) 행의 실행이 쓰는데 시험 기대 목록(설계서 출력 표 · 소스 분석)에 없는 프로그램 객체 → {"rows", "known",
    "sequences", "added", "settable"}(소스 소견의 한 종류, 두 프로파일). 입력 보완과 같은 객체 규칙(`_source_object_decl`) —
    volatile · 부동소수 객체도 소견에는 든다(`settable` False — 기대 열로는 더하지 않는다, 리뷰 R80 I8). 목록이 그 객체를 담은
    객체(구조체 · 펼치지 않은 배열)를 적었으면 적은 것이다(리뷰 R80 W6)."""
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    if not scope:
        return {}
    design = set(_design_outputs(unit))
    added = ((unit.get("source_written_outputs") or {}).get("added")) or {}
    out: Dict[str, Dict[str, Any]] = {}
    for n, r in source_written_names(sequences).items():
        why = _source_object_decl(scope, n)[1]
        if n in design or any(c in design for c in _containers(n)) or (why and why not in _FINDING_ONLY):
            continue
        out[n] = {"rows": r["rows"], "known": r["known"], "sequences": r["sequences"], "added": n in added,
                  "settable": not why}
    return out


def _function_local_names(unit: Dict[str, Any]) -> Optional[set]:
    """Names the unit's function declares — parameters and block-scope locals at any depth (`boundary_rows.
    _declared_locals`); None when the function does not parse."""
    from generators.boundary_rows import _declared_locals
    from generators.c_source_oracle import Unsupported, _parsed_function
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    parser = cpc_shared_parser()
    if parser is None or not unit.get("source_text") or not scope:
        return None
    raw = str(unit["source_text"]).encode()
    try:
        _root, fn, _shared = _parsed_function(parser, raw, str(unit.get("name") or ""), scope)
    except Unsupported:
        return None
    names = set(_declared_locals(fn.child_by_field_name("body"), raw))
    stack = [fn.child_by_field_name("declarator")]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        if node.type == "parameter_declaration":
            d = node.child_by_field_name("declarator")
            while d is not None and d.type != "identifier":
                d = d.child_by_field_name("declarator")
            if d is not None:
                names.add(raw[d.start_byte:d.end_byte].decode())
            continue
        stack.extend(node.named_children)
    return names


def cpc_shared_parser():
    from generators import c_project_context as _cpc
    return _cpc.shared_parser()


def listed_outputs_not_written(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> Tuple[List[str], str]:
    """(R80) (기대 목록이 적은 이 번역 단위의 객체인데 함수도, 함수가 부르는 함수도 쓰지 않는 것, 판정하지 않은 사유) — 프로젝트
    쓰기 closure(`scope["effects"]`)로 판정한다. 사유가 있으면 목록은 비고 판정하지 않은 것이다(리뷰 R80 W5 — '없음' 과
    가른다): closure 없음 · 모르는 피호출 · 포인터 쓰기 · 함수가 지역도 모델 객체도 아닌 이름에 쓴다(그것을 거쳐 쓸 수 있다) ·
    함수를 읽지 못함. 함수가 선언한 지역 · 매개변수는 쓰기 대상이 아니다(closure 가 블록 안 지역을 쓰기로 셀 수 있다).
    어느 행의 실행이 쓴 이름도 아니다. 반환값 · stub 표기 · 매개변수 대상은 대상 밖."""
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    closure = (((scope.get("effects") or {}).get("functions")) or {}).get(str(unit.get("name") or ""))
    if not isinstance(closure, dict):
        return [], "no_write_closure"
    if closure.get("unknown_callees"):
        return [], "unknown_callees"
    if closure.get("pointer_write"):
        return [], "pointer_write"
    objects = set(scope.get("globals") or {}) | set(scope.get("arrays") or {}) | set(scope.get("struct_globals") or {})
    roots = {re.split(r"[\[.]", str(w), maxsplit=1)[0] for w in closure.get("writes") or ()}
    if any(w not in objects for w in roots):
        local = _function_local_names(unit)
        if local is None:
            return [], "function_unparsed"
        if any(w not in objects and w not in local for w in roots):
            return [], "writes_unmodeled_name"
    writes = {w for w in roots if w in objects}
    written = set(source_written_names(sequences))
    out: List[str] = []
    for name in _design_outputs(unit):
        root = re.split(r"[\[.]", name, maxsplit=1)[0]
        if name == _RETURN_VAR or "()" in name or root not in objects or name in written or root in writes:
            continue
        out.append(name)
    return out, ""


def summarize_source_written_outputs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """품질 리포트 `source_written_outputs`(확장 프로파일) — 더한 unit · 이름(회차 · 마지막 보완), 값이 안 서 다시 뺀 이름(그 출력
    때문에 더한 입력이 남은 것 포함), 값이 한 번도 서지 않아 더하지 않은 이름, 더하지 않은 사유, 상한 · 오류."""
    recs = [u.get("source_written_outputs") for u in units if isinstance(u.get("source_written_outputs"), dict)]
    not_added = Counter(why for r in recs for why in (r.get("not_added") or {}).values())
    return {"units": len(recs), "units_with_added": sum(1 for r in recs if r.get("added")),
            "names_added": sum(len(r.get("added") or {}) for r in recs),
            "names_added_final": sum(1 for r in recs for a in (r.get("added") or {}).values() if a.get("round") == "final"),
            "names_dropped_underived": sum(len(r.get("dropped") or {}) for r in recs),
            "inputs_kept_for_dropped": sum(1 for r in recs for d in (r.get("dropped") or {}).values() if d.get("input_kept")),
            "names_never_known": sum(len(r.get("never_known") or []) for r in recs),
            # (review R82 I-R3-2) harness buffer elements written past what the row names (no column)
            "names_written_past_allocation": sum(len(r.get("written_past_allocation") or []) for r in recs),
            # (review R80 W7) late columns whose unwritten paths need an initial value no round could add
            "names_final_initial_not_in_inputs": sum(len(r.get("final_initial_not_in_inputs") or []) for r in recs),
            "rows_written_error": sum(int(r.get("rows_written_error") or 0) for r in recs),
            "not_added": dict(not_added),
            "units_output_columns_full": sum(1 for r in recs if "output_columns_full" in (r.get("not_added") or {}).values()),
            # (R82) a pointer parameter's buffer whose first `_BUFFER_ELEMENTS_MAX` elements already were columns
            "units_buffer_elements_full": sum(1 for r in recs
                                              if "buffer_elements_full" in (r.get("not_added") or {}).values()),
            "buffer_elements_max": _BUFFER_ELEMENTS_MAX,
            "max_rounds": max((int(r.get("rounds") or 0) for r in recs), default=0),
            "units_round_cap_reached": sum(1 for r in recs if r.get("round_cap_reached")),
            # (R81 review I-R3-3) the pointee-column drop still dropping after its re-applies
            "units_pointee_rerun_cap_reached": sum(1 for r in recs if r.get("pointee_rerun_cap_reached")),
            "errors": sum(1 for r in recs if r.get("error") or r.get("final_error"))}


# (R80) the unit keys the extended generation's rounds change — restored when the completion fails, and (R86) the
#   columns the reference-scale document takes over (one tuple, so a key added here reaches both — review R86 I4)
_EXTENDED_COLUMN_KEYS = ("input_vars", "source_input_types", "value_domains", "design_input_vars", "design_value_domains",
                         "output_vars", "design_output_vars")


def extended_unit_sequences(unit: Dict[str, Any], reference_cap: Optional[int] = _DEFAULT_SEQ_COUNT,
                            type_cache: Optional[Dict[str, str]] = None, keep_code_rows: bool = False
                            ) -> List[Dict[str, Any]]:
    """(R19) 확장 프로파일의 unit 시퀀스 — 경계 행 없이 만들고 → 소스가 읽는 입력을 더해 다시 만들고 → 경계 행을 **한 번** 붙인다
    (리뷰 R1 W6: 첫 판은 경계 탐색을 두 번 했다). 입력 보완이 실패하면 그 unit 은 설계 입력 목록 그대로 만든다(선택 확장이 문서를
    잃게 하지 않는다 — R15 규칙). ``type_cache``: `generate_sequences` 의 명시 타입 맵(영향도 초안 — 프로세스 전역을 쓰지 않는다).
    ``keep_code_rows``(R86): 회차가 쓴 코드 기준 행 캐시를 `unit["_code_rows_kept"]` 로 남긴다(`reference_unit_sequences`)."""
    # (R85) `reference_cap`: 같은 SCM 의 정본 규모 문서가 쓴 상한 — 확장 문서의 앞부분이 그 문서다(리뷰 R85 C1)
    def _gen() -> List[Dict[str, Any]]:
        return generate_sequences(unit, None, extended=True, boundary_rows=False, reference_cap=reference_cap,
                                  type_cache=type_cache)
    seqs = _gen()
    snapshot = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                for k in _EXTENDED_COLUMN_KEYS if (v := unit.get(k)) is not None}
    try:
        seqs = complete_source_read_inputs(unit, seqs, _gen)
    except Exception as exc:  # noqa: BLE001 — an optional extension never costs the document; the unit records why
        _logger.warning("SUTS 소스 읽기 입력 보완 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        for k in _EXTENDED_COLUMN_KEYS:
            unit.pop(k, None)
        unit.update(snapshot)
        unit["source_read_inputs"] = {"error": type(exc).__name__, "added": {}, "not_added": {}, "rounds": 0,
                                      "remaining": {}}
        unit["source_written_outputs"] = {**_new_written_record(), "error": type(exc).__name__}
        seqs = _gen()
    # (R85) the reference-scale code rows of the rounds — the same search each round
    _cache = unit.pop("_code_rows_cache", None)
    if keep_code_rows and _cache is not None:
        unit["_code_rows_kept"] = _cache
    seqs = append_boundary_rows(unit, seqs)
    # (R80) 회차 뒤에 붙은 행이 쓴 객체까지 — 경계 · 설계 범위 밖 시나리오 행만 닿는 경로(enum default 등)
    seqs = complete_source_written_outputs(unit, seqs)
    _record_remaining(unit, seqs)
    return seqs


# (R86) what the reference-scale document takes from the extended generation: its columns, and the two records that say
#   where they came from (`_prior_input_names` · `_added_inputs` read them while the block is built)
_REFERENCE_COLUMN_KEYS = _EXTENDED_COLUMN_KEYS + ("source_read_inputs", "source_written_outputs")
# (review R86 W1) what the written-output completion sets only when it has something to say — a value pass 1 left
#   describes the extended rows, so the reference-scale pass counts afresh
_WRITTEN_RECOUNT_KEYS = ("written_past_allocation", "final_initial_not_in_inputs", "pointee_rerun_cap_reached")


def _block_view(seqs: List[Dict[str, Any]]) -> List[Tuple[str, str, str]]:
    """(review R86 W2) a row as the reference-scale document states it — name, inputs, the derived expected values."""
    out = []
    for s in seqs:
        ev = s.get("expected_evidence") or {}
        stated = {k: v for k, v in (s.get("expected") or {}).items() if (ev.get(k) or {}).get("status") == "derived"}
        out.append((str(s.get("strategy") or ""), json.dumps(s.get("inputs") or {}, sort_keys=True, default=str),
                    json.dumps(stated, sort_keys=True, default=str)))
    return out


def reference_unit_sequences(unit: Dict[str, Any], max_seq: Optional[int] = _DEFAULT_SEQ_COUNT,
                             type_cache: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """(R86) 정본 규모 문서 — 열은 확장 생성이 정한 것(소스가 읽는 입력 R19 · 소스가 쓰는 출력 R80 · 그 입력의 고정값), 행은
    정본 규모 블록(R85, 행 수 그대로).

    R85 뒤에도 정본만 잡는 변이(KJPDS02_PV 246 · HDPDM01 158)의 대부분은 정본 규모 문서의 **열**이 설계서 입출력 표뿐이라서였다:
    함수가 읽는 입력이 열에 없어 출력 값을 정하지 못하거나(`s_MotorSpeedModeSelection_RearSet` 입력 2 개 — 확장은 12 개를 더해
    출력 4 개를 정한다) 정본이 쓰는 입력이 생성 열에 없었다(`sf_LinUdsSecurityAccess` 의 응답 버퍼 원소). R19 · R80 이 그 열을
    찾았지만 확장 프로파일에만 넣었다(R78 · R85 와 같은 '확장에만 고침'). 확장 문서의 앞 블록은 정본 규모 블록과 같은 행이므로
    (R85 — 두 프로젝트 모든 함수에서 이름 · 순서 · 값 같음) 그 블록을 확장의 열로 적으면 정본 규모 문서가 잡던 것은 그대로 잡는다.

    두 단계: ① 이 unit 으로 `extended_unit_sequences` 를 돌려 열을 정하고, 그 열 키(`_REFERENCE_COLUMN_KEYS`)만 남긴다 — 확장
    생성이 unit 에 남긴 다른 기록(MC/DC 설계 · 경계 탐색 · 중복 행 · 관측 쌍 …)은 확장 행을 가리키므로 지운다(행만 걸러 내면
    그 기록이 없는 행을 가리킨다) ② 그 열 위에서 정본 규모 생성(`generate_sequences(unit, max_seq)`) — MC/DC 쌍 확정 · 중복 행 ·
    코드 기준 행 기록이 이 문서의 행만으로 서고, 더한 입력은 확장 블록과 같은 고정값이며, 코드 기준 행은 ①의 회차가 찾은 것을
    쓴다(같은 탐색 문맥이면 — 리뷰 R86 W2: 회차 뒤 더한 출력이 oracle 의 관측 · 버퍼 할당을 바꿔 새로 찾으면 다를 수 있다). 그 뒤
    이 문서의 행이 값을 내지 못한 더한 출력은 다시 빼고(`complete_source_written_outputs`) 남은 이름을 이 행으로 센다. ②의 행이
    ①의 확장 문서 앞 블록과 다르면 `block_mismatch` 로 남긴다(R75 포함 관계의 상시 점검 — 공시). ① 이나 ② 가 실패하면 설계서
    열로 만들고 사유를 남긴다(`reference_columns.error`). 시간은 확장 생성만큼 든다(공시)."""
    before = set(unit)
    snapshot = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                for k in _REFERENCE_COLUMN_KEYS if (v := unit.get(k)) is not None}
    design_in, design_out = list(unit.get("input_vars") or []), list(unit.get("output_vars") or [])

    def _restore() -> None:
        for k in set(unit) - before:
            unit.pop(k, None)
        for k in _REFERENCE_COLUMN_KEYS:
            unit.pop(k, None)
        unit.update(snapshot)

    error, block, cache = None, None, None
    try:
        ext = extended_unit_sequences(unit, max_seq, type_cache=type_cache, keep_code_rows=True)
        block = _block_view([s for s in ext if not is_extended_strategy(s.get("strategy"))])
        del ext   # (review R86 I-R2-3) the extended rows and their evidence are not needed past this point
        cache = unit.pop("_code_rows_kept", None)
    except Exception as exc:  # noqa: BLE001 — the columns are an addition; the document keeps its design columns
        _logger.warning("SUTS 정본 규모 열(확장 생성) 실패(%s): %s", unit.get("name"), exc, exc_info=True)
        error = type(exc).__name__
    # (review R86 I2) a completion error inside the extended generation keeps the design columns there — said here too
    #   (review R86 I-R2-1) and the written-output completion's own final error
    partial = {f"{k}{suffix}": rec.get(f) for k in ("source_read_inputs", "source_written_outputs")
               for f, suffix in (("error", ""), ("final_error", ".final"))
               if isinstance(rec := unit.get(k), dict) and rec.get(f)} if not error else {}
    for k in set(unit) - before - set(_REFERENCE_COLUMN_KEYS):
        unit.pop(k, None)
    seqs: Optional[List[Dict[str, Any]]] = None
    if not error:
        if cache is not None:
            unit["_code_rows_cache"] = cache   # the reference-scale generation pops it when done
        rec = unit.get("source_written_outputs")
        for k in (_WRITTEN_RECOUNT_KEYS + ("final_error",)) if isinstance(rec, dict) else ():
            rec.pop(k, None)   # pass 1's final error is in `extension_errors`; pass 2 records its own
        try:
            seqs = generate_sequences(unit, max_seq, type_cache=type_cache)
            seqs = complete_source_written_outputs(unit, seqs)
            _recount_final_initial(unit, seqs)
            _record_remaining(unit, seqs)
        except Exception as exc:  # noqa: BLE001 — review R86 I1: the extended columns never cost the document
            _logger.warning("SUTS 정본 규모 생성(확장 열) 실패(%s): %s", unit.get("name"), exc, exc_info=True)
            error, seqs = f"reference_pass:{type(exc).__name__}", None
        unit.pop("_code_rows_cache", None)
    if error:
        _restore()
        seqs = generate_sequences(unit, max_seq, type_cache=type_cache)
    mismatch = None
    if not error and block is not None:
        mine = _block_view(seqs)
        if [m[0] for m in mine] != [b[0] for b in block]:
            mismatch = "names"
        elif [m[1] for m in mine] != [b[1] for b in block]:
            mismatch = "inputs"
        elif mine != block:
            mismatch = "expected"
    unit["reference_columns"] = {
        # (review R86 I-R2-2) a unit that fell back reports its error only — not also the pass-1 partial errors
        "error": error, "extension_errors": {} if error else partial, "block_mismatch": mismatch,
        "inputs_added": 0 if error else len([v for v in unit.get("input_vars") or [] if v not in design_in]),
        "outputs_added": 0 if error else len([v for v in unit.get("output_vars") or [] if v not in design_out])}
    return seqs


def _recount_final_initial(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> None:
    """(review R86 W1) the late (final-round) written outputs whose unwritten path needs an initial value no column gives —
    counted over these rows (pass 1 counted the extended rows)."""
    rec = unit.get("source_written_outputs")
    if not isinstance(rec, dict):
        return
    finals = {n for n, a in (rec.get("added") or {}).items() if (a or {}).get("round") == "final"}
    left = sorted(n for n in finals if any(
        str((ev or {}).get("reason") or "").startswith(UNWRITTEN_OUTPUT_PREFIX)
        for s in sequences for k, ev in (s.get("expected_evidence") or {}).items() if k == n))
    if left:
        rec["final_initial_not_in_inputs"] = left
    else:
        rec.pop("final_initial_not_in_inputs", None)


def input_list_gaps(unit: Dict[str, Any], sequences: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """함수가 초기값을 읽는데 시험 입력 목록에 없던 **프로그램 객체** → {"slots", "sequences", "added"}(소스 소견의 한 종류).

    R19 가 더한 이름 — 이 문서에선 막힌 칸이 아니므로 칸 수·행 번호는 0/빈 목록이다(처음 본 칸 수는 품질 리포트
    `source_read_inputs.slots_first_seen`, 리뷰 R1 W5) — 과 여전히 값 없이 읽는 이름이다(R86 부터 두 프로파일 — 정본 규모 문서도
    확장 생성이 정한 열을 쓴다; 확장 생성이 실패한 unit 은 문서 행의 사유에서 본 이름). 지역·멤버 경로·모르는 이름은 입력 목록의 결손이 아니다."""
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    objects = set(scope.get("globals") or {}) | set(scope.get("arrays") or {})
    rec = unit.get("source_read_inputs") if isinstance(unit.get("source_read_inputs"), dict) else {}
    # (백로그 2-c) 함수 실행 모델에서 읽힌 근거 없이, 쓰지 않은 출력의 관측에만 필요했던 이름은 결손 소견이 아니다(소견은 근거가
    #   있는 이름만)
    final = source_read_names(sequences)
    # (리뷰 2차 I-e) 더한 회차엔 읽힌 근거가 없었어도 마지막 행(MC/DC 벡터가 비운 칸 등)이 읽어 막혔으면 결손이다
    # (review R81 W6) a pointer parameter's pointee R19 added (`ctx[0].bitcount`) is no program object the input list
    #   lacks — the design names the parameter; its notation is the pointer-parameter record's (`pointer_parameters`).
    #   The rule of the loop below (review R81 C-R2-1: cutting at `.` too dropped R39 struct members `g.a`, which are
    #   objects of their own name)
    gaps: Dict[str, Dict[str, Any]] = {n: {"slots": 0, "sequences": [], "added": True}
                                       for n, a in (rec.get("added") or {}).items()
                                       if n.partition("[")[0] in objects
                                       and (not isinstance(a, dict) or a.get("read_on_model", True)
                                            or (final.get(n) or {}).get("read"))}
    # (R21 리뷰 W1) 한 행(GLOBAL)이 설정해 열로 보인 이름도, 다른 행이 값 없이 읽으면 입력 목록의 결손이다
    shown = set(((unit.get("row_io_columns") or {}).get("inputs_shown")) or [])
    inputs = set(unit.get("input_vars") or []) - shown
    for name, r in final.items():
        if r.get("read") and name not in inputs and name not in gaps and name.partition("[")[0] in objects:
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
                for k in ("basis", "assumptions", "stubs", "assumed_undefined", "callees_interpreted", "callees_effects_only",
                          "observed_only_pointees", "exact_width_guards",   # (review R81 I-R3-2 · R83 I-R2-4)
                          "possible_ub_on_forked_path"):                    # (R90 review W1)
                    ev.pop(k, None)
                ev.update(status="unknown", oracle_kind="none", reason=reason)
                seq.setdefault("expected", {})[var] = f"{VERIFY_PREFIX} {reason}"
                record["downgraded_slots"] += 1
        _rewrite_expected_line(seq)
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
            # (백로그 2-c) 그중 함수 실행 모델에서 읽힌 근거 없이, 쓰지 않은 출력의 최종값 관측에만 필요했던 이름
            "names_added_for_unwritten_outputs": sum(1 for r in recs for a in (r.get("added") or {}).values()
                                                     if isinstance(a, dict) and a.get("read_on_model") is False
                                                     and not a.get("prior_value_for_write")),
            # (R82) 그중 쓰기 삭제가 드러나게 쓰기 전 값을 정하려고 더한 이름(함수는 그 객체를 쓴다 — 읽지 않는다)
            # (review R82 I1) only those no row or search reads (a name the search also needed is counted there)
            "names_added_for_write_prior_value": sum(1 for r in recs for a in (r.get("added") or {}).values()
                                                     if isinstance(a, dict) and a.get("prior_value_for_write")
                                                     and a.get("read_on_model") is False),
            # (review R82 W5 · W8) prior values not added (by why) and left at the round cap — apart from the reads
            "prior_value_not_added": dict(sorted(Counter(why for r in recs for why in (
                r.get("prior_value_not_added") or {}).values()).items())),
            "prior_values_beyond_cap": sum(len(r.get("prior_values_beyond_cap") or []) for r in recs),
            # (review R82 I-R5-4) fixed values moved off the value the function writes · names every candidate collides
            "prior_fixed_values_moved": sum(len(r.get("prior_fixed_values") or {}) for r in recs),
            "prior_fixed_values_collide": sum(len(r.get("prior_fixed_values_collide") or []) for r in recs),
            # (R78) 그중 어떤 행도 아니라 동작 시나리오 탐색이 닿지 못한 경로에서 읽은 이름 — 행의 칸 수는 0 이다(리뷰 R78 W5)
            "names_added_by_scenario_search": sum(1 for r in recs for a in (r.get("added") or {}).values()
                                                  if isinstance(a, dict) and a.get("scenario_targets")),
            "slots_first_seen": sum(int(a.get("slots") or 0) for r in recs for a in (r.get("added") or {}).values()),
            "not_added": dict(sorted(not_added.items())),
            "units_input_columns_full": sum(1 for r in recs if "input_columns_full" in (r.get("not_added") or {}).values()),
            # (R82) a pointer parameter's buffer whose first `_BUFFER_ELEMENTS_MAX` elements already were columns
            "units_buffer_elements_full": sum(1 for r in recs
                                              if "buffer_elements_full" in (r.get("not_added") or {}).values()),
            "buffer_elements_max": _BUFFER_ELEMENTS_MAX,
            "max_rounds": max((int(r.get("rounds") or 0) for r in recs), default=0),
            # (R59) 회차 상한과, 상한이 탐색을 자른 unit(다음 회차가 더했을 이름이 있었다) · 그 이름 수
            "round_cap": _SOURCE_READ_ROUNDS,
            "units_round_cap_reached": sum(1 for r in recs if r.get("round_cap_reached")),
            "names_beyond_cap": sum(len(r.get("names_beyond_cap") or []) for r in recs),
            "units_with_remaining": sum(1 for r in recs if r.get("remaining")),
            "names_remaining": sum(len(r.get("remaining") or {}) for r in recs),
            "errors": sum(1 for r in recs if r.get("error"))}


def attach_unit_sources(units: List[Dict[str, Any]], source_files: Optional[Dict[str, str]],
                        project_context: Optional[Dict[str, Any]] = None,
                        stats: Optional[Dict[str, Any]] = None) -> int:
    """unit 에 정의 파일의 원문을 붙인다(`source_files` = 소스 단계의 파일당 1회 맵). 붙인 unit 수를 돌려준다.

    원문은 소스 oracle(`apply_sequence_evidence`)과 MC/DC 소스 경로의 입력이다. 맵에 없으면(잘려 읽힘·원격 미확보)
    비워 두고 사유를 남긴다 — 빈 원문을 "지원 안 되는 코드" 로 오독하지 않게 `source_unavailable_reason` 이 말한다.

    (R81) `project_context`(소스 단계 `project_context`)가 있으면 unit 마다 정의 파일의 번역 단위 범위(`project_scope` —
    typedef·매크로·열거자·전역·`#if` 상태)를 붙인다. 같은 파일의 unit 은 한 범위 객체를 공유한다(복사 없음).

    (R62) 범위가 붙은 파일은 `apply_body_projection` 으로 읽는다 — 식 가운데를 가르는 `#if` 때문에 트리가 깨진 함수를
    컴파일러처럼 판정된 팔만 남겨 다시 읽은 원문(같은 파일의 unit 은 그 원문 하나를 공유). ``stats`` 에 집계를 담는다
    (`summarize_body_projection`).
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
        from generators.c_project_context import apply_body_projection
        paths = [str(u.get("source_path") or "") for u in units if u.get("source_text")]
        scopes = build_scopes(project_context, [p for p in paths if p in project_context["files"]])
        # (리뷰 전 자체 점검) 경로가 아니라 (경로, 원문) 마다 — unit 이 미리 가진 원문이 파일 원문과 다르면 그 원문 그대로
        # 둔다(범위와 해시가 안 맞는 원문은 `apply_body_projection` 이 바꾸지 않는다). 같은 원문은 한 번만 투영한다.
        texts: Dict[tuple, str] = {}
        for unit in units:
            path = str(unit.get("source_path") or "")
            scope = scopes.get(path)
            if scope is not None and unit.get("source_text"):
                key = (path, unit["source_text"])
                if key not in texts:
                    texts[key] = apply_body_projection(scope, unit["source_text"])
                unit["source_text"] = texts[key]
                unit["project_scope"] = scope
        if stats is not None:
            # (리뷰 W5a) 문서에 행이 있는 함수(이 unit 들)만 센다 — 같은 파일의 다른 함수는 `outside_document` 로
            from generators.c_project_context import summarize_body_projection
            stats.update(summarize_body_projection(
                scopes.values(), only={(str(u.get("source_path") or ""), str(u.get("name") or "")) for u in units
                                       if u.get("project_scope") is not None}))
    return attached


def normalize_pointer_parameters(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """(R81) 설계서가 포인터 매개변수를 **포인터 이름으로만** 적은 입출력(`u16p_Peak` · `ctx`)을 가리키는 대상 표기(정본 표기)로.

    생성기는 그 칸의 값을 가리키는 대상의 값으로 써 왔지만(`_mcdc_declared_domains`), 소스 oracle 은 포인터 자리의 값을 주소로
    읽어(R40 리뷰 W4 — 행이 적은 `NULL` · 주소) 대상을 만들지 않았다 — KJPDS02_PV 확장(R80 코드)에서 정본만 판별한 변이 137 중
    ≈92 가 생성 문서에 확정 칸이 하나도 없는 포인터 매개변수 함수(`s_sha256_init` 38 · `s_AutoClose_ApplyTip2Run_Normal` 14 ·
    `s_ApplyTemperatureCompensation` 12 …)에 있었고, 정본은 `u16p_Peak[0]` · `s32p_speed[0]` · `ctx[0].state[1]` 을 입력 ·
    기대값으로 적었다.

    - 스칼라 대상(`U16 *u16p_Peak`): `u16p_Peak` → `u16p_Peak[0]`(입력 · 출력 · 설계 범위 · 값 집합의 열쇠). 행의 값은 예전 그대로
      대상의 값이고, oracle 은 그 값으로 하네스 객체를 만든다.
    - 구조체 대상 입력(`SHA256_CTX *ctx`): 값 하나로 설정할 수 없다 — 함수 본문이 닿는 대상 멤버(`ctx[0].bitcount` ·
      `ctx[0].state[0]` …, R40 `_read_pointee_names`)로 바꾸고(입력 열 상한 안 — 설계의 뒤 입력 자리는 남긴다), 닿는 멤버가
      없으면 뺀다. 함수를 읽지 못해 닿는 멤버를 **모르면** 손대지 않는다(리뷰 R81 W2 — '없음' 과 가른다).
    - 구조체 대상 출력은 그대로 둔다 — 행이 그 매개변수를 관측하면 oracle 이 대상을 만들고(`_Interp.observes_pointee`), 확장
      프로파일이 실행이 쓴 멤버를 기대값 열로 더한다(R80 출력 축).
    대상 배치를 소스가 모르면(void · 미해석 타입 · 전처리 공백) 손대지 않고 사유를 센다. unit 마다 따로 — 한 unit 의 실패는 그
    unit 만 설계서 이름 그대로 두고 사유를 남긴다(리뷰 R81 W5). 기록 `unit["pointer_parameters"]`, 집계를 돌려준다(품질 리포트
    · 공시 `pointer_parameters`)."""
    max_inp = _INPUT_COL_END - _INPUT_COL_START + 1
    totals: Dict[str, Any] = {"units": 0, "renamed": 0, "struct_inputs_replaced": 0, "struct_inputs_dropped": 0,
                              "member_inputs_added": 0, "members_over_cap": 0, "struct_outputs_observed": 0,
                              "unmodeled": Counter(), "errors": 0, "samples": [], "dropped_inputs": []}
    for unit in units:
        try:
            rec = _normalize_unit_pointers(unit, max_inp)
        except Exception as exc:  # noqa: BLE001 — this unit keeps the design's names; the record says why
            _logger.warning("SUTS 포인터 매개변수 표기 실패(%s): %s", unit.get("name"), exc, exc_info=True)
            unit["pointer_parameters"] = {"error": type(exc).__name__}
            totals["errors"] += 1
            continue
        if rec is None:
            continue
        totals["units"] += 1
        totals["renamed"] += len(rec["renamed"])
        totals["struct_inputs_replaced"] += sum(1 for v in rec["replaced"].values() if v)
        totals["struct_inputs_dropped"] += sum(1 for v in rec["replaced"].values() if not v)
        totals["dropped_inputs"] += [f"{unit.get('name')}.{p}" for p, v in rec["replaced"].items() if not v]
        totals["member_inputs_added"] += len(rec["members_added"])
        totals["members_over_cap"] += len(rec["over_cap"])
        totals["struct_outputs_observed"] += len(rec["outputs_observed"])
        totals["unmodeled"].update(v.split(":", 1)[0] for v in rec["unmodeled"].values())
        if (rec["renamed"] or rec["replaced"]) and len(totals["samples"]) < 6:
            changes = [f"{p}→{q}" for p, q in rec["renamed"].items()] + \
                [f"{p}→{'·'.join(v[:2]) + ('…' if len(v) > 2 else '') if v else '(뺌)'}" for p, v in rec["replaced"].items()]
            totals["samples"].append(f"{unit.get('name')}: {', '.join(changes[:3])}")
    totals["unmodeled"] = dict(totals["unmodeled"])
    return totals


def _normalize_unit_pointers(unit: Dict[str, Any], max_inp: int) -> Optional[Dict[str, Any]]:
    """(R81) 한 unit — 바꾼 것의 기록(`unit["pointer_parameters"]`), 포인터 매개변수 이름이 목록에 없으면 None."""
    from generators.c_source_oracle import Unsupported, _parsed_function
    from generators.mcdc_design import _pointee_core, _pointer_params, _read_pointee_names
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else None
    if not scope:
        return None
    fn = str(unit.get("name") or "")
    params = _pointer_params(scope, fn)
    ins, outs = list(unit.get("input_vars") or []), list(unit.get("output_vars") or [])
    hit = [n for n in dict.fromkeys(ins + outs) if n in params]
    if not hit:
        return None
    layouts = scope.get("pointee_types") or {}
    renamed: Dict[str, str] = {}
    replaced: Dict[str, List[str]] = {}
    unmodeled: Dict[str, str] = {}
    accessed: Optional[List[str]] = None
    unread = ""
    for p in hit:
        layout = layouts.get(_pointee_core(params[p])) or {}
        if not layout or layout.get("reason"):
            unmodeled[p] = str(layout.get("reason") or "pointee_layout_unknown")
            continue
        if set(layout.get("members") or {}) == {""} and not layout.get("arrays"):
            renamed[p] = p + "[0]"
            continue
        if p not in ins:
            continue
        if accessed is None and not unread:
            parser = cpc_shared_parser()
            if parser is None or not unit.get("source_text"):
                unread = "function_unread:" + ("tree_sitter_unavailable" if parser is None else "no_source_text")
            else:
                raw = str(unit["source_text"]).encode()
                try:
                    _root, node, _shared = _parsed_function(parser, raw, fn, scope)
                    accessed = _read_pointee_names(node.child_by_field_name("body"), raw, scope, fn)
                except Unsupported as exc:
                    unread = "function_unread:" + str(exc)
        if accessed is None:
            unmodeled[p] = unread   # (review R81 W2) the members it reaches are unknown — the design's name stays
            continue
        replaced[p] = [n for n in accessed if n.startswith(p + "[0].")]
    new_ins: List[str] = []
    cut: List[str] = []
    for i, n in enumerate(ins):
        for m in ([renamed[n]] if n in renamed else replaced[n] if n in replaced else [n]):
            if m in new_ins:
                continue
            if n in replaced and len(new_ins) + (len(ins) - i - 1) >= max_inp:
                cut.append(m)   # the design's later inputs keep their columns
                continue
            new_ins.append(m)
    if renamed or replaced:
        unit["input_vars"] = new_ins
        unit["output_vars"] = list(dict.fromkeys(renamed.get(n, n) for n in outs))
        # the design's range · value set of the parameter is its pointee's (the cell held the pointee's value); the
        #   pointee's type comes from the source layout (`pointee_input_types`) — `param_types` keeps the pointer's own
        #   declaration (`U16 *`) for the readers that ask what the parameter is
        for key in ("uds_param_info", "value_domains"):
            table = unit.get(key)
            if isinstance(table, dict):
                for p, q in renamed.items():
                    if p in table and q not in table:
                        table[q] = table.pop(p)
    members = {m for v in replaced.values() for m in v}
    rec = {"design_inputs": ins, "design_outputs": outs, "renamed": renamed, "replaced": replaced, "over_cap": cut,
           "members_added": [m for m in new_ins if m in members and m not in ins],
           "outputs_observed": [p for p in outs if p in params and p not in renamed and p not in unmodeled],
           "unmodeled": unmodeled}
    unit["pointer_parameters"] = rec
    return rec


def summarize_document_body_projection(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """(R62) 본문 #if 투영 집계 — 문서 함수는 **최종 unit 목록**(시험 범위 `apply_scope` 로 좁힌 뒤)이다. 범위를 붙일 때의
    목록(`attach_unit_sources` 의 ``stats``)으로 세면 문서에 행이 없는 함수(HDPDM01 LIN 스택)의 투영을 이 문서의 것으로
    공시한다. 범위가 붙은 unit 이 없으면 빈 dict."""
    from generators.c_project_context import summarize_body_projection
    scopes = {id(u["project_scope"]): u["project_scope"] for u in units if u.get("project_scope") is not None}
    if not scopes:
        return {}
    return summarize_body_projection(
        scopes.values(), only={(str(u.get("source_path") or ""), str(u.get("name") or "")) for u in units
                               if u.get("project_scope") is not None})


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
                           # (R36) 피호출 stub 반환값(`F() return`)을 행에 넣어 설계한 결정·쌍 — 그 행은 F 가 stub 일 때만 성립
                           "stub_input_decisions": 0, "stub_input_pairs": 0, "stub_input_pairs_retained": 0,
                           # (R36) 2차 탐색(stub 값)을 받은 결정 · 조건을 더한 결정 — 예산은 1차와 별도(함수당 같은 한도)
                           "stub_search_decisions": 0, "stub_search_improved": 0, "stub_search_errors": 0,
                           # (R37) 조건 안에 호출이 있는 결정 — 함수 실행 모델로 따로(별도 예산) 탐색한 결정 · 그중 설계
                           "call_condition_decisions": 0, "call_condition_designed": 0,
                           # (R39) 구조체 멤버(`g.a`)를 읽는 조건의 결정 — 따로(별도 예산) 탐색한 결정 · 그중 설계
                           "member_condition_decisions": 0, "member_condition_designed": 0,
                           # (R40) 포인터 매개변수가 가리키는 대상(`p->a`)을 읽거나 그 널 검사가 있는 결정 — 따로(별도 예산)
                           "pointee_condition_decisions": 0, "pointee_condition_designed": 0,
                           # (R76) 배열 원소(`g_a[1]` · 상수 표 · 첨자)를 읽는 조건의 결정 — 따로(별도 예산) 탐색한 결정 · 그중 설계
                           "element_condition_decisions": 0, "element_condition_designed": 0,
                           # (R77) 상수 첨자 원소(`g_a[POS]`)를 식 엔진이 입력으로 읽은 결정 · 상태별 · 원소를 읽고도 받지 못해
                           #   R76 경로(같은 사유 · 같은 탐색)로 보낸 결정과 그 사유(앞부분) · 쌍의 행을 함수 실행 모델로
                           #   다시 돌린 결과(주장과 같음 / 결정에 닿지 않음 / 판단 불가 — 다르면 그 결정은 R76 경로로 갔다)
                           "element_expression_decisions": 0, "element_expression_designed": 0,
                           "element_expression_partial": 0, "element_expression_no_pair": 0,
                           "element_expression_refused": 0, "element_expression_refusals": {},
                           "element_run_members": 0, "element_run_agrees": 0, "element_run_unreached": 0,
                           "element_run_not_checked": 0, "element_pairs_withdrawn": 0,
                           # (R58, 확장) 기본 설계가 쌍을 못 만든 결정을 소스가 읽어 더한 입력까지 써서 다시 설계 — 대상 ·
                           #   채택(2차 설계의 결과로 바꾼 결정) · 그중 설계 · 2차 설계가 실패해 기본 설계를 유지한 함수
                           "source_read_pass_decisions": 0, "source_read_pass_adopted": 0,
                           "source_read_pass_designed": 0, "source_read_pass_errors": 0,
                           "source_read_pass_designed_refused_for_added": 0,
                           # (R60, 확장) 유지 쌍의 두 행이 출력으로 갈리는가 — 이미 갈림 · 탐색으로 찾은 쌍(행 더함) · 못 찾음
                           #   (도출 출력은 있으나 같음 / 도출 출력 없음) · 예산 · 확인 못 함 · 근거 불일치 · 실패한 함수
                           "observable_pairs": 0, "observable_searched": 0, "observable_masked": 0,
                           "observable_underived": 0, "observable_recheck_refused": 0, "observable_no_candidate": 0,
                           "observable_copy_only": 0, "observable_searched_own_rows": {},
                           "observable_budget_exhausted": 0, "observable_not_checked": 0,
                           "observable_evidence_mismatch": 0, "observable_rows": 0, "observable_errors": 0,
                           "observable_evaluations": 0,
                           # (R71) 쌍을 다 못 만든 결정 중 탐색이 상한에 닿은 결정 — 종류별(한 결정이 여러 종류) · 상태별
                           #   (`mcdc_design.search_limits` — 'MCDC Design' 시트 'Search Limit' 열과 같은 판정)
                           "search_limited_decisions": 0, "search_limits": dict.fromkeys(SEARCH_LIMITS, 0),
                           # (R71 리뷰 N2) 상한에는 닿지 않고 표본 값(도메인보다 좁음)만 본 결정 — 거의 모든 탐색의 성질이라
                           #   '상한에 닿은 결정' 에서 뺀다(종류별 `search_limits.sampled_values` 는 둘을 합친 수)
                           "sampled_only_decisions": 0,
                           "search_limited_by_status": {"partial": 0, "no_pair_found": 0, "unsupported": 0},
                           # (R71) 쌍당 후보 상한에서 멈춘 Observable 쌍 — 상태(masked 등)는 그 후보까지만 본 결과
                           "observable_candidates_capped": 0,
                           # (R72) 진리값 곱 상한(조건 12)보다 조건이 많아 조건마다 짝지은 결정(식 엔진) · 그중 설계
                           "wide_decisions": 0, "wide_designed": 0,
                           # (R73) 같은 결정을 함수 실행 모델이 조건마다 표적 탐색한 결정(별도 그룹 · 예산) · 그중 설계
                           "wide_path_decisions": 0, "wide_path_designed": 0,
                           "execution_status": "not_run", "reachability": "unverified"}
    out["units_not_analyzed"] = 0
    # (R56 리뷰 I1) 함수 실행 모델 탐색 예산 — 문서가 어느 예산으로 설계됐는지(같은 소스라도 예산이 다르면 쌍이 다르다)
    budgets = set()
    for unit in units:
        report = unit.get("mcdc_design")
        if not report:
            # 입출력이 없어 전략 목록을 쓰지 않는 unit(조기 반환) — 분석 안 한 것이지 결정이 없는 것이 아니다.
            out["units_not_analyzed"] += 1
            continue
        out["units"] += 1
        b = report.get("budgets") or {}
        if b.get("max_path_runs") is not None:
            budgets.add((int(b["max_path_runs"]), int(b.get("max_path_steps") or 0)))
        obs = unit.get("observable_mcdc") or {}
        out["observable_rows"] += int(obs.get("rows") or 0)
        out["observable_errors"] += bool(obs.get("error") or obs.get("confirm_error"))   # (리뷰 R60 3차 W4)

        out["observable_evaluations"] += int(obs.get("evaluations") or 0)
        srp = report.get("source_read_pass") or {}
        out["source_read_pass_decisions"] += int(srp.get("decisions_searched") or 0)
        out["source_read_pass_adopted"] += int(srp.get("decisions_adopted") or 0)
        out["source_read_pass_designed"] += int(srp.get("decisions_designed") or 0)
        out["source_read_pass_errors"] += bool(srp.get("error"))
        out["source_read_pass_designed_refused_for_added"] += int(srp.get("designed_refused_for_added") or 0)
        stub_search = report.get("stub_search") or {}
        out["stub_search_decisions"] += int(stub_search.get("decisions_searched") or 0)
        out["stub_search_improved"] += int(stub_search.get("decisions_improved") or 0)
        out["stub_search_errors"] += bool(stub_search.get("error"))   # 2차 탐색이 실패해 1차 결과로 되돌린 함수
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
            limits = search_limits(d)
            if limits and all(kind == "sampled_values" for kind, _detail in limits):
                out["sampled_only_decisions"] += 1
            elif limits:
                out["search_limited_decisions"] += 1
                out["search_limited_by_status"][status if status in ("partial", "no_pair_found") else "unsupported"] += 1
            for kind, _detail in limits:
                out["search_limits"][kind] += 1
            # (R40 리뷰 W6) 어느 별도 탐색을 받았는지는 거부 사유 문자열이 아니라 설계기가 붙인 표식으로 센다 —
            #   널 검사(`parameter_domain_unresolved:p`)로 들어온 결정도 빠지지 않는다
            group = {"call_in_condition": "call", "struct_member": "member", "pointee": "pointee",
                     "array_element": "element"}.get(
                str(d.get("search_group") or "")) if d.get("evaluation") == "source_path" else None
            if group:
                out[f"{group}_condition_decisions"] += 1
                out[f"{group}_condition_designed"] += status == "designed"
            if d.get("expression_elements"):
                out["element_expression_decisions"] += 1
                out["element_expression_designed"] += status == "designed"
                out["element_expression_partial"] += status == "partial"
                out["element_expression_no_pair"] += status == "no_pair_found"
                run = d.get("element_run_check") or {}
                for key in ("members", "agrees", "unreached", "not_checked"):
                    out[f"element_run_{key}"] += int(run.get(key) or 0)
                out["element_pairs_withdrawn"] += len(d.get("unreached_pairs") or [])
            elif d.get("element_expression_reason"):
                out["element_expression_refused"] += 1
                why = str(d["element_expression_reason"]).split(":")
                # ``array_element_binding_unverified:<array>:<kind>`` → 종류까지(배열 이름은 빼고), 나머지는 첫 토큰
                key = f"{why[0]}:{why[2]}" if why[0] == "array_element_binding_unverified" and len(why) > 2 else why[0]
                out["element_expression_refusals"][key] = out["element_expression_refusals"].get(key, 0) + 1
            if d.get("pair_search") == "per_condition":
                out["wide_decisions"] += 1
                out["wide_designed"] += status == "designed"
            elif d.get("pair_search") == "path_targeted":
                out["wide_path_decisions"] += 1
                out["wide_path_designed"] += status == "designed"
            if d.get("stub_inputs"):
                out["stub_input_decisions"] += 1
            for pair in d.get("pairs") or []:
                if pair.get("stub_inputs"):
                    out["stub_input_pairs"] += 1
                    out["stub_input_pairs_retained"] += pair.get("retained_status") == "retained"
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
                ob = (pair.get("observable") or {}).get("status")
                if ob == "searched":
                    # (리뷰 R60 4차 W1) 내역도 쌍 표시에서 센다 — 확인에서 강등된 쌍은 빠진다(상태 수와 같은 출처)
                    own = str((pair.get("observable") or {}).get("own_rows") or "unknown")
                    out["observable_searched_own_rows"][own] = out["observable_searched_own_rows"].get(own, 0) + 1
                if ob:
                    key = {"observable": "observable_pairs", "searched": "observable_searched"}.get(ob, f"observable_{ob}")
                    out[key] = out.get(key, 0) + 1
                    out["observable_candidates_capped"] += bool((pair.get("observable") or {}).get("candidates_capped"))
                out["conditions_paired"] += 1
                key = {"retained": "retained_pairs", "invalidated": "invalidated_pairs"}.get(
                    pair.get("retained_status"), "truncated_pairs")
                out[key] += 1
    # 탐색 그룹·탐색(1차 · stub 값)마다의 한도. 한 생성 안에서는 하나 — 여럿이면(호출부가 따로 준 예산) 전부 적는다
    out["path_search_budget"] = [{"max_path_runs": r, "max_path_steps": s} for r, s in sorted(budgets)] or None
    return out


def _summarize_source_findings(units: List[Dict[str, Any]], all_sequences: Dict[str, List[Dict[str, Any]]]):
    from generators import source_findings as sf
    out = sf.summarize_findings(sf.collect_findings(units, all_sequences, {}))
    # (R19) 입력 목록 밖 읽기는 미정의 동작 소견과 따로 센다(`findings` 는 그대로 UB 소견 수)
    gaps = sf.collect_input_gap_findings(units, _input_list_gaps(units, all_sequences), {})
    out["input_list_gaps"] = sf.summarize_input_gaps(gaps)
    # (R80) 출력 목록 밖 쓰기 · 함수가 쓰지 않는 설계 출력 — 같은 시트의 다른 종류
    gaps, listed, undecided = _output_list_findings(units, all_sequences)
    out["output_list_gaps"] = sf.summarize_output_gaps(
        sf.collect_output_gap_findings(units, gaps, listed, {}), undecided,
        # (review R80 W-R2-4) rows whose written record failed: their writes are in no finding
        rows_written_error=sum(1 for u in units for s in all_sequences.get(u["fid"]) or []
                               if s.get("source_written_error")))
    return out


def _judgeable_design_outputs(unit: Dict[str, Any]) -> List[str]:
    """(review R80 I-R2-4) Design outputs `listed_outputs_not_written` would judge — this unit's program objects (no
    return value, stub notation or parameter target)."""
    scope = unit.get("project_scope") if isinstance(unit.get("project_scope"), dict) else {}
    objects = set(scope.get("globals") or {}) | set(scope.get("arrays") or {}) | set(scope.get("struct_globals") or {})
    return [n for n in _design_outputs(unit) if n != _RETURN_VAR and "()" not in n
            and re.split(r"[\[.]", n, maxsplit=1)[0] in objects]


def _output_list_findings(units: List[Dict[str, Any]], all_sequences: Dict[str, List[Dict[str, Any]]]):
    """(R80) unit 마다 (출력 목록 밖 쓰기, 함수가 쓰지 않는 설계 출력, 그것을 판정하지 않은 사유 — 설계 출력이 있는 unit 만)."""
    gaps = {u["fid"]: output_list_gaps(u, all_sequences.get(u["fid"]) or []) for u in units}
    listed, undecided = {}, {}
    for u in units:
        names, why = listed_outputs_not_written(u, all_sequences.get(u["fid"]) or [])
        listed[u["fid"]] = names
        if why and _judgeable_design_outputs(u):
            undecided[u["fid"]] = why
    return gaps, listed, undecided


def _input_list_gaps(units: List[Dict[str, Any]], all_sequences: Dict[str, List[Dict[str, Any]]]
                     ) -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {u["fid"]: input_list_gaps(u, all_sequences.get(u["fid"]) or []) for u in units}


def _mcdc_vector_key(inputs: Dict[str, Any]) -> str:
    return json.dumps(inputs, sort_keys=True)


def _mcdc_slot(seq: Dict[str, Any]) -> int:
    """MC/DC 벡터 행(`MCDC_<n>`)이 쓰는 벡터의 번호 — 기본 설계 벡터 뒤가 2차 설계(R58) 벡터다. 숫자가 아닌 이름은 -1."""
    m = re.fullmatch(r"MCDC_(\d+)", _catalog_name(seq.get("strategy")))
    return int(m.group(1)) if m else -1


def _mcdc_source_read_pass(unit: Dict[str, Any], base_report: Dict[str, Any],
                           declared_domains: Callable[[], Dict[str, Dict[str, Any]]], added_inputs: List[str]
                           ) -> Optional[Dict[str, Any]]:
    """(R58, 확장 프로파일) 소스가 읽어 더한 입력(R19)까지 행 입력으로 써서, 기본 설계(설계 입력 목록 위)가 쌍을 **하나도**
    못 만든 결정만 다시 설계한다.

    기본 설계의 결정 · 벡터 · 자리는 그대로다(정본 규모 문서와 포함 관계, R75) — 새 쌍의 벡터는 확장 자리에만 붙고, 쌍이
    있던 결정(부분 설계 포함)은 바꾸지 않는다(기본 행의 라벨이 정본 규모 문서와 갈린다). 채택하는 결정: 2차 설계가 쌍을
    찾았거나, 기본 설계가 더한 입력을 읽는다는 이유로 거절한 결정(그 결정의 사유는 모든 입력으로 본 2차 설계의 것이 맞다).
    `base_report` 의 결정 자리를 채택한 결정으로 바꾸고 `source_read_pass` 기록을 남긴다. 반환: 2차 보고서 · 그 unit · 채택한
    결정 · 새 벡터(결정 순서), 채택이 없으면 None."""
    wanted = {d["occurrence_id"] for d in base_report.get("decisions") or []
              if d.get("status") in ("unsupported", "no_pair_found") and not d.get("pairs")}
    record: Dict[str, Any] = {"decisions_searched": len(wanted), "decisions_adopted": 0, "decisions_designed": 0,
                              "vectors": 0}
    base_report["source_read_pass"] = record
    if not wanted:
        return None
    ext_unit = dict(unit)
    ext = build_mcdc_design(ext_unit, declared_domains=declared_domains(), only_occurrences=wanted)
    by_occurrence = {d["occurrence_id"]: d for d in ext.get("decisions") or []}
    added = set(added_inputs)
    adopted: List[Any] = []
    vectors: List[Dict[str, Any]] = []
    wide_vectors: List[Dict[str, Any]] = []   # (R72 리뷰 W2) 조건마다 짝지은 결정의 벡터 — 다른 결정의 2차 벡터 뒤로
    seen: set = set()
    for i, base in enumerate(base_report["decisions"]):
        if base.get("occurrence_id") not in wanted:
            continue
        new = by_occurrence.get(base["occurrence_id"])
        if new is None or new.get("status") == "not_requested":
            continue
        reason = str(base.get("reason") or "")
        reads_added = reason.startswith("decision_variable_not_in_unit_inputs:") and reason.split(":", 1)[1] in added
        if not new.get("pairs") and not reads_added:
            # (R71 리뷰 I3) 채택하지 않은 결정은 기본 설계의 상태 · 사유 · 탐색 상한을 그대로 보인다 — 2차 설계의 상한(예산 ·
            #   값 목록)은 보이는 결과의 것이 아니라 적지 않는다(채택한 결정은 2차 설계의 기록을 가진다)
            continue
        new["input_scope"] = "with_source_read_inputs"
        new["design_input_reason"] = reason   # 기본 설계(설계 입력 목록 위)가 쌍을 못 만든 사유
        # (리뷰 R58 I1) 쌍의 두 행에서 값이 다른 더한 입력(사실 기록 — 비어도 더한 입력에 **값이 있어서** 생긴 쌍일 수 있다:
        #   `g_b < g_a` 는 g_b 를 고정한 채 g_a 만 움직인다. 리뷰 R58 W-A)
        new["source_read_inputs_moved"] = sorted({k for pr in new.get("pairs") or [] for k in added
                                                  if (pr.get("inputs_a") or {}).get(k) != (pr.get("inputs_b") or {}).get(k)})
        new["design_refused_for_added_input"] = reads_added
        adopted.append((i, new))
    for wide in (False, True):
        for _i, new in adopted:
            if (new.get("pair_search") in ("per_condition", "path_targeted")) is not wide:   # (R73) both engines
                continue
            for pair in new.get("pairs") or []:
                for side in ("a", "b"):
                    key = _mcdc_vector_key(pair[f"inputs_{side}"])
                    if key not in seen:
                        seen.add(key)
                        (wide_vectors if wide else vectors).append(pair[f"inputs_{side}"])
    vectors.extend(wide_vectors)
    # 다 고른 뒤에 한 번에 바꾼다 — 도중 실패가 기본 보고서를 반쯤 바꾼 채 남기지 않게
    for i, new in adopted:
        base_report["decisions"][i] = new
    record.update(decisions_adopted=len(adopted),
                  decisions_designed=sum(d.get("status") == "designed" for _, d in adopted), vectors=len(vectors),
                  # (리뷰 R58 W-A) 기본 설계가 '더한 입력을 읽는다' 로 거절한 결정 — 그 입력이 행에 있어 설계됐다. 나머지(다른
                  #   사유로 쌍이 없던 경로 설계 결정)는 더한 입력에 값이 생긴 실행과 2차 탐색의 새 예산 중 무엇 덕인지 가르지 않는다
                  designed_refused_for_added=sum(d.get("status") == "designed" and bool(d.get("design_refused_for_added_input"))
                                                 for _, d in adopted),
                  # (리뷰 R58 I2) 2차 설계의 stub 값 탐색 기록 — 집계(`stub_search_*`)는 기본 설계 것만 센다
                  stub_search=ext.get("stub_search"))
    if not adopted:
        return None
    return {"report": ext, "unit": ext_unit, "decisions": [d for _, d in adopted], "vectors": vectors}


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

    return apply_sequence_evidence(unit, sequences, written=True)   # (review R80 W2) the writes, as the first pass


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
    # (R80) + 출력 목록 밖 쓰기 · 함수가 쓰지 않는 설계 출력
    from generators.source_findings import (
        collect_findings,
        collect_input_gap_findings,
        collect_output_gap_findings,
        write_source_findings_sheet,
    )
    write_source_findings_sheet(
        wb, collect_findings(units, all_sequences, rendered_tc_ids)
        + collect_input_gap_findings(units, _input_list_gaps(units, all_sequences), rendered_tc_ids)
        + collect_output_gap_findings(units, *_output_list_findings(units, all_sequences)[:2], rendered_tc_ids),
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
                 "Search Complete",
                 # (R71) 쌍을 다 못 만든 결정의 탐색이 닿은 상한(`mcdc_design.search_limits`) — 빈칸은 상한 없이 끝난 탐색
                 "Search Limit",
                 "Execution", "Reachability", "Evaluation", "Possible UB", "Stub Inputs",
                 # (R58) 설계한 행 입력 목록 — design_inputs(설계서 입력 표) · with_source_read_inputs(소스가 읽어 더한 입력까지)
                 "Input Scope",
                 # (R60, 확장) 쌍의 두 행이 소스 oracle 출력으로 갈리는가 · 갈리는 두 행(탐색으로 더한 행이면 그 번호)
                 "Observable", "Observable Sequences"]


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
            # (R62 리뷰 I8) 투영한 함수의 결정식은 지운 지시문 · 팔이 공백 줄로 남는다 — 공백뿐인 줄만 걷어 보인다
            common = [re.sub(r"\n[ \t]*(?=\n)", "", str(decision.get("expression") or "")),
                      decision.get("status", ""), decision.get("reason", ""),
                      decision.get("source_kind", ""), decision.get("source_hash", ""),
                      "yes" if decision.get("search_complete") else "no",
                      " · ".join(f"{kind}:{detail}" if detail else kind for kind, detail in search_limits(decision)),
                      "not_run", "unverified",
                      # (R2c) expression = 결정식만 평가 · source_path = 함수 실행 모델(지역변수·결정 전 갱신 포함)
                      decision.get("evaluation") or "expression"]
            pairs = decision.get("pairs") or []
            # (R36) 쌍의 행이 설정하는 피호출 stub 반환값(쌍 단위 — 1차 탐색 쌍은 비어 있다) — 실행 환경에서 그 함수가
            #   stub 이어야 그 쌍이 성립한다. 쌍 없는 결정 행은 결정 단위(2차 탐색 쌍이 없으면 비어 있다)
            stubs = ", ".join(decision.get("stub_inputs") or [])
            scope = decision.get("input_scope") or "design_inputs"
            if not pairs:
                # 쌍 없는 결정도 한 행 — 빠지면 "MC/DC 설계 완료" 로 오독된다(분모에서 사라진다).
                ws.append([tc_id, unit.get("name", ""), decision.get("decision_id", ""), "", "", "", "", "", "", "",
                           "", "", "", "", *common, "", stubs, scope, "", ""])
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
                           *common, "+".join(ub), ", ".join(pair.get("stub_inputs") or []), scope,
                           *_observable_cells(pair.get("observable"))])
    # 한 번에 서식 — 결정마다 ``ws.max_row``(= 전 셀 ``max``)를 부르면 결정 수 × 셀 수로 커진다
    for row_cells in ws.iter_rows(min_row=2):
        for cell in row_cells:
            cell.font = data_font
            if isinstance(cell.value, str):
                cell.data_type = "s"   # 식·JSON 이 `=`·`-` 로 시작해도 수식으로 읽히지 않게
    ws.auto_filter.ref = ws.dimensions
    for idx, _ in enumerate(_MCDC_HEADERS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = 40 if idx in (8, 9, 15, 17, 19) else 16


def _observable_cells(mark: Optional[Dict[str, Any]]) -> List[str]:
    """(R60) 'Observable' · 'Observable Sequences' 칸 — 확장 프로파일만 상태가 있다(정본 규모 문서는 빈칸)."""
    if not mark:
        return ["", ""]
    seqs = f"{mark.get('seq_a')},{mark.get('seq_b')}" if mark.get("seq_a") is not None else ""
    status = str(mark.get("status") or "")
    if mark.get("reason"):
        status += ":" + str(mark["reason"])   # (리뷰 R60 3차 I2) not_checked:<사유>
    elif mark.get("own_rows"):
        status += f" [own:{mark['own_rows']}]"   # (리뷰 R60 4차 I5) 쌍 자신의 두 행이 왜 모자랐는지
    if mark.get("candidates_capped"):
        status += f" [candidates_capped:{mark.get('candidates_tried')}]"   # (R71) 남은 후보를 보지 않은 판정
    return [status, seqs]


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
        # (R66 리뷰 2차 W-B) override 스냅샷 등급이 최종 등급을 정한 unit 수(SwUDS 가 없거나 더 낮음)
        "asil_decided_by_override": sum(1 for u in units if u.get("asil_by_override")),
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
def _resolved_doc_input(path: Optional[str], label: str, report: Optional[Dict[str, Any]] = None):
    """문서 입력(SRS/UDS/HSIS)을 **로컬에서 열 수 있는 경로**로 확보한다.

    과거엔 `Path(p).is_file()`만 봤다. cloudium 모드에서 U:\\ 같은 경로는 backend 프로세스에
    권한이 없어(worker exe만 접근 가능) 항상 False가 되고, 보강 블록이 **경고 한 줄 없이**
    통째로 skip됐다 — 산출물엔 "요구 ID 없음"으로만 남아 원인을 알 수 없었다.

    로컬에 있으면 원래 경로를 그대로 돌려주고(추가 I/O 0), worker에만 있으면 resolver로
    bytes를 읽어 임시 파일로 materialize한 뒤 종료 시 지운다. 어느 쪽도 아니면 None을
    yield하되 **사유를 warning으로 남긴다**.

    (R66, 감사 #1) ``report`` 를 주면 그 dict 에 ``opened`` · ``reason`` 을 적는다 — 로그만 남기면 공시가 "보강 실패 0건 —
    전부 끝까지 돌았다" 를 말했다(보강 블록이 문서를 못 열면 예외 없이 건너뛰므로 `enrichment_errors` 에 안 든다).
    사유에는 파일 이름만 쓴다(경로는 로그에만).

    Yields: 열 수 있는 로컬 경로(str) 또는 None.
    """
    raw = str(path or "").strip()
    rec = report if report is not None else {}
    rec["opened"] = False
    if not raw:
        yield None
        return
    try:
        if Path(raw).is_file():
            rec["opened"] = True
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
        rec["reason"] = f"로컬에 없고 파일 접근기(resolver)도 쓸 수 없음 ({type(exc).__name__})"
        yield None
        return

    try:
        if not resolver.is_file(raw):
            _logger.warning("%s 입력을 건너뜀 — resolver(mode=%s)에도 없음: %s",
                            label, getattr(resolver, "mode", "?"), raw)
            rec["reason"] = (f"파일 없음(접근 방식 {getattr(resolver, 'mode', '?')}) — 경로가 바뀌었거나 "
                             "문서가 이동/개정됐을 수 있다")
            yield None
            return
        data = resolver.read_bytes(raw)
    except Exception as exc:
        _logger.warning("%s 입력 읽기 실패 — 보강 생략: %s (%s)", label, raw, exc)
        rec["reason"] = f"읽기 실패 ({type(exc).__name__})"
        yield None
        return
    rec["opened"] = True

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
    input_skips: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Top-level SUTS generation pipeline.

    Args (추가):
        input_skips: (R66) 호출자(라우트)가 지정된 입력 문서를 로컬화하지 못한 사유 ``"<라벨>: <사유>"``(라벨 SRS · SDS ·
            UDS · HSIS). 그 문서는 경로가 None 으로 오지만 '주지 않음' 이 아니라 '지정했지만 열지 못함' 으로 공시한다.
        tc_profile: `""`/`"extended"`(기본, R87) = 확장 — 시퀀스 상한 없이 + 확장 전략(`extended_unit_sequences`; 정본이 잡는
            변이를 다 잡는 쪽). `"reference"`/`"recommended"` = 정본 규모(함수당 `max_sequences` 행, R85 블록 · R86 열).
            단일 정의는 `generators/tc_profile.py`(`DOC_DEFAULT_PROFILE`).
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
    # (R66) 없거나 못 읽으면 빈 맵 — 저장소 docs/ 의 다른 프로젝트 SDS 로 대체하지 않는다(`read_sds_input`)
    _sds_map, _sds_reading = read_sds_input(sds_docx_path, skipped=input_skip_reason(input_skips, "SDS"))
    # (R66, 감사 #1) 입력 문서를 열었나 — 문서마다 한 기록(`note_input_document`). 보강 블록은 문서를 못 열면 예외 없이
    #   건너뛰므로 `enrichment_errors` 에 안 들고, 예전 공시는 "보강 실패 0건 — 전부 끝까지 돌았다" 를 말했다.
    _input_docs: Dict[str, Dict[str, Any]] = {"SDS": dict(_sds_reading, blocks_unopened=[] if _sds_reading.get("read")
                                                           or not _sds_reading.get("given") else ["sds_partitions"])}

    _progress(30, "유닛 함수 수집 중")
    # ── SwUDS 입출력 표 — 시험 변수 이름의 **정본 출처** ──────────────────────
    # ⚠ 여기서 읽는다. 아래 UDS 보강 블록(설명·설계 ID)은 `collect_unit_functions`
    #   **뒤**라 늦다 — 이름 대체는 배열 원소 확장보다 앞서야 하고, 확장은 collect
    #   안에서 일어난다. 문서를 두 번 materialize 하는 비용(cloudium 경유)은 감수한다.
    _uds_io: Optional[Dict[str, Any]] = None
    _open_rec: Dict[str, Any] = {}
    with _resolved_doc_input(uds_path, "UDS(입출력)", report=_open_rec) as _uds_io_local:
        note_input_document(_input_docs, "UDS", uds_path, "uds_unit_io", _open_rec, input_skips)
        if _uds_io_local:
            try:
                from generators.uds_unit_io import load_uds_unit_io
                # (R65) 표 Name 행 별칭은 소스 함수 목록으로 확인한 것만 쓴다(`restrict_aliases`)
                _uds_io = load_uds_unit_io(_uds_io_local, source_functions=_source_function_names(function_details))
            except Exception as _e:  # noqa: BLE001 — 실패하면 소스 파싱으로 간다
                _logger.warning("SwUDS 입출력 읽기 실패 — 소스 파싱 이름을 쓴다: %s", _e)
    units = collect_unit_functions(function_details, globals_info_map, sds_map=_sds_map,
                                   uds_io_map=_uds_io,
                                   struct_members=report_data.get("struct_member_arrays") or {})
    attach_unit_sources(units, report_data.get("source_files"), report_data.get("project_context"))
    # (R81) 포인터 이름만 적힌 매개변수 → 가리키는 대상 표기(정본 표기) — 범위(대상 배치)가 붙은 뒤, 행을 만들기 전
    try:
        _pointer_parameters = normalize_pointer_parameters(units)
    except Exception as exc:  # noqa: BLE001 — the names stay as the design wrote them; the report says why
        _logger.warning("SUTS 포인터 매개변수 표기 실패: %s", exc, exc_info=True)
        _pointer_parameters = {"error": type(exc).__name__}

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

    _open_rec = {}
    with _resolved_doc_input(srs_docx_path, "SRS", report=_open_rec) as _srs_local:
        _srs_rec = note_input_document(_input_docs, "SRS", srs_docx_path, "srs_req_ids", _open_rec, input_skips)
        if _srs_local:
            _progress(36, "SRS 요구사항 ID 보강 중")
            try:
                from generators.sts import load_uds_design_ids as _sts_design_ids
                from generators.sts import map_requirements_to_functions, parse_srs_docx_tables
                srs_reqs = parse_srs_docx_tables(_srs_local)
                # (R66, 감사 #41) 요구 표를 하나도 못 읽은 SRS 는 '열었다' 로 끝나지 않는다 — 요구 ID 가 없는 이유가 그것이다
                _srs_rec["requirements"] = len(srs_reqs or [])
                if not srs_reqs:
                    _srs_rec["reason"] = _srs_rec.get("reason") or "요구 표 0 개(SRS 양식이 다르거나 SRS 가 아닌 문서)"
                if srs_reqs:
                    _design_ids: Dict[str, Any] = {}
                    _open_bridge: Dict[str, Any] = {}
                    with _resolved_doc_input(uds_path, "UDS(설계 ID 브리지)", report=_open_bridge) as _uds_bridge:
                        note_input_document(_input_docs, "UDS", uds_path, "uds_design_id_bridge", _open_bridge, input_skips)
                        if _uds_bridge:
                            _design_ids = _sts_design_ids(_uds_bridge) or {}
                    # (R66) SDS 가 없으면 빈 맵 — 설계서 파티션 · 설계 ID 브리지 경로가 꺼진다(다른 프로젝트 SDS 로 잇지 않는다)
                    _req_to_fids = map_requirements_to_functions(
                        srs_reqs, function_details, sds_map=_sds_map, uds_design_ids=_design_ids or None)
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
    _open_rec = {}
    with _resolved_doc_input(uds_path, "UDS", report=_open_rec) as _uds_local:
        note_input_document(_input_docs, "UDS", uds_path, "uds_description_design_ids", _open_rec, input_skips)
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
                _design = load_uds_design_ids(_uds_local, source_functions=_source_function_names(function_details))
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
    _open_rec = {}
    with _resolved_doc_input(hsis_path, "HSIS", report=_open_rec) as _hsis_local:
        note_input_document(_input_docs, "HSIS", hsis_path, "hsis_signals", _open_rec, input_skips)
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
    # (R87) 미설정 · 모르는 값은 기본(확장) — 정본이 잡는 변이를 다 잡는 쪽(사용자 결정 2026-10-15)
    _profile, _profile_bad = normalize_tc_profile(tc_profile, "suts")
    _extended = _profile == TC_PROFILE_EXTENDED
    if _profile_bad:
        _logger.warning("SUTS: 모르는 tc_profile %r — 기본(확장)으로 만든다", _profile_bad)
    all_sequences: Dict[str, List[Dict[str, Any]]] = {}
    ai_enhanced = 0
    for i, unit in enumerate(units):
        # (R19) 확장: 소스가 읽는데 입력 목록에 없는 객체를 선언 타입으로 더해 다시 만든다.
        # (R86) 정본 규모도 확장 생성이 정한 열 위에서(소스가 읽는 입력 · 쓰는 출력) — 행은 정본 규모 블록 그대로
        seqs = extended_unit_sequences(unit, max_sequences) if _extended else reference_unit_sequences(unit, max_sequences)
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
    # (R75) 어느 프로파일로 만들었나 · 확장 전략이 덧붙인 시퀀스 수(정본 규모면 0).
    quality["tc_profile"] = _profile
    quality["tc_profile_unknown_value"] = _profile_bad
    # (R76 N104) 세 생성기가 같은 두 키로 "요청한 상한 / 실제로 건 상한" 을 말한다(SITS 가 먼저 썼다). `None` = 상한 없음.
    quality["caps_requested"] = {"max_sequences": max_sequences}
    quality["caps_effective"] = {"max_sequences": None if _extended else max_sequences}
    quality["enrichment_errors"] = _enrich_errors
    # (R66, 감사 #1 · #62) 입력 문서마다 지정했나 · 열었나 · 못 연 사유 · 그 때문에 건너뛴 블록(SDS 는 파티션 수까지).
    #   주지 않은 문서도 적는다(given False — 블록마다 부르므로 네 문서가 늘 있다) — 공시가 '주면 무엇이 채워지는가' 를 말한다.
    quality["input_documents"] = _input_docs
    quality["extended_sequences"], _beyond = profile_increment(all_sequences, _extended)
    # (R17) #if verdicts on build-configuration evidence — units, reasons, names taken as undefined
    from generators.c_project_context import summarize_build_assumptions
    quality["build_assumptions"] = summarize_build_assumptions(u.get("project_scope") for u in units)
    # (R62) 식 가운데를 가르는 #if 로 트리가 깨졌던 함수 — 투영한 것과, 오류가 남은 것의 사유(두 프로파일).
    #   ⚠ 문서 함수는 **최종 unit 목록**(설계 ID 범위로 좁힌 뒤)으로 센다 — 범위를 붙일 때의 목록에는 문서에 행이 없는
    #   함수(HDPDM01 LIN 스택)가 있어, 그 함수의 투영을 "이 문서의 투영" 으로 공시했다(R62 확인)
    quality["body_projection"] = summarize_document_body_projection(units)
    # (R65) SwUDS 를 어떻게 읽었나 — 머리말 이름 · 표 Name 별칭 · 세로 병합 행 · 이름으로 못 읽은 행 · Value Range 판독
    quality["uds_reading"] = summarize_uds_reading(_uds_io, units, bool(_input_docs["UDS"].get("given")),
                                                   _source_function_names(function_details))
    quality["uds_const_inputs"] = summarize_uds_const_inputs(units)     # (R67)
    quality["pointer_parameters"] = _pointer_parameters                  # (R81)
    # (R68, 감사 #16) 소스 단계가 끝내 읽지 못한 파일과, 그 파일에 정의가 있어 원문 없이 남은 unit
    quality["source_read_failures"] = summarize_source_read_failures(report_data.get("source_read_failures"), units)
    if (_input_docs["UDS"].get("given") and "uds_unit_io" in (_input_docs["UDS"].get("blocks_unopened") or [])
            and not quality["uds_reading"].get("read_error")):
        # (R66) 입출력 표를 읽을 SwUDS 를 열지 못했으면 '함수 표 0 개' 로 적지 않는다 — 원인은 파일 접근이다.
        #   (리뷰 W2) 뒤 블록(설명 · 설계 ID 브리지)만 못 연 것이면 입출력 표는 읽었다 — 그건 입력 문서 항목이 말한다
        quality["uds_reading"]["read_error"] = f"열지 못함 — {_input_docs['UDS'].get('reason') or '사유 미상'}"
    # (R63) 문서 함수가 읽는 C 파일(정의 파일 · include 한 헤더)을 어떻게 읽었나 — 벤더 구문을 공백으로 읽은 곳, 파서 트리가 못 본
    #   파일 수준 지시문(구조체 선언 안 #define 등), 줄 이음을 걷고 읽은 여러 줄 매크로, 남은 구문 오류, 문맥이 못 읽은 파일
    from generators.c_project_context import summarize_source_reading
    quality["source_reading"] = summarize_source_reading(report_data.get("project_context"),
                                                         [u.get("project_scope") for u in units])
    # (R64) 포인터로 쓰는 callee · stub 이 실제로 가리킬 수 있는 객체만 지우는가 — 분석이 대상을 특정한 함수와 못 한 원인
    from generators.pointer_flow import summarize_pointer_targets_all
    # (R89 리뷰 W2) 소스 루트가 둘 이상이면 빌드마다 closure 하나 — 첫 unit 의 것만 세면 한 빌드만 보고된다
    quality["pointer_targets"] = summarize_pointer_targets_all(
        (u.get("project_scope") or {}).get("effects") for u in units)
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
            # (R78) 동작 시나리오 행을 더한 기준으로 쓴 탐색 — 따로 정한 예산 · 상한이라 따로 센다
            "extra_bases_units": sum(1 for b in _bsearch if b.get("extra_bases")),
            "extra_boundaries": sum(int(b.get("extra_boundaries") or 0) for b in _bsearch),
            "extra_evaluations": sum(int(b.get("extra_evaluations") or 0) for b in _bsearch),
            "extra_budget_exhausted": sum(1 for b in _bsearch if b.get("extra_evaluation_budget_exhausted")
                                          or b.get("extra_boundary_cap_reached")),
            # 상태의 사유 꼬리(`oracle_underived:<reason>`)는 분포에서 떼어 종류로 센다
            "not_searched": dict(Counter(str(b.get("status")).split(":", 1)[0] for b in _bsearch
                                         if b.get("status") != "searched")),
            "units_without_search": len(units) - len(_bsearch)}
        # (R19) MC/DC 채움 행 — 벡터가 비운 결정 무관 입력을 채운 동반 행(쌍 주장 없음)
        _fills = [u.get("mcdc_fill") for u in units if isinstance(u.get("mcdc_fill"), dict)]
        quality["mcdc_fill"] = {k: sum(int(f.get(k) or 0) for f in _fills)
                                for k in ("mcdc_rows", "rows_with_blanks", "rows", "not_fillable", "duplicates", "pruned")}
        quality["mcdc_fill"]["units_with_rows"] = sum(1 for f in _fills if f.get("rows"))
        quality["mcdc_fill"]["errors"] = sum(1 for f in _fills if f.get("error"))
        # (R83) 피호출 값 구별 행 — 같은 값을 돌려주던 stub 을 서로 다른 값으로 옮긴 동반 행
        quality["stub_apart"] = summarize_stub_apart(units)
        # (R84) 결함 전파 행 — 그 자리의 값을 바꾸면 관측 출력이 달라지는 행(설계 범위 안, 못 찾은 것만 설계 범위 밖 FI)
        quality["propagation_rows"] = summarize_propagation_rows(units)
        # (R31) 설계 범위 밖 강건성 행 — 직접 비교 상수가 설계 범위 밖·타입 안인 입력, 상한에 잘린 점, 실패 unit
        quality["robustness_rows"] = summarize_robustness_rows(units)
        # (R78) 동작 시나리오 행 — 닿은 문장 · 분기 결과의 분모, 못 닿은 것, 예산 · 상한에 잘린 것
        quality["scenario_rows"] = summarize_scenario_rows(units)
    # 확장은 시퀀스 상한도 푼다 — 기본 카탈로그 안에 있었지만 상한(`max_sequences`)에 잘리던 자리가 이제 나온다.
    #   위 수와 합치면 기본 문서 대비 증분이다(입출력 없는 unit 은 전략 목록을 쓰지 않아 0).
    quality["sequences_beyond_reference_cap"] = _beyond
    # (R19) 소스가 읽어 더한 입력 — 설계서 입력 목록과 달라지는 열이라 분모와 사유를 함께 공시한다. (R80) 소스가 써서 더한
    #   기대값 — 설계서 출력 목록과 달라지는 열. (R86) 두 프로파일 — 정본 규모 문서도 확장 생성이 정한 열을 쓴다
    quality["source_read_inputs"] = summarize_source_read_inputs(units)
    quality["source_written_outputs"] = summarize_source_written_outputs(units)
    if not _extended:
        quality["reference_columns"] = summarize_reference_columns(units)
    # (R85) 정본 규모 문서의 코드 기준 행(두 프로파일 — 확장 문서의 정본 규모 블록에도 같은 행이 있다)
    quality["reference_code_rows"] = summarize_reference_code_rows(units)

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
    for _doc, _rec in _input_docs.items():
        if _rec.get("given") and not input_document_usable(_doc, _rec):
            validation.setdefault("warnings", []).append(
                f"지정한 {_doc} 를 쓰지 못했다 — {_rec.get('reason') or '사유 미상'} (그 문서가 채울 값이 이 문서에 없다)")
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
