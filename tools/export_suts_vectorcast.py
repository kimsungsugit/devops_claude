from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openpyxl import load_workbook

_TC_SHEET = "2.SW Unit Test Spec"
_DATA_START_ROW = 7
_COMPONENT_COL = 2
_TC_ID_COL = 3
_NAME_COL = 4
_DESCRIPTION_COL = 5
_TEST_METHOD_COL = 8
_GEN_METHOD_COL = 9
_PRECONDITION_COL = 10
_SEQUENCE_TEXT_COL = 11
_TC_GEN_METHOD_COL = 12
_SEQ_NO_COL = 13
_INPUT_COL_START = 14
_INPUT_COL_END = 62
_OUTPUT_COL_START = 63
_OUTPUT_COL_END = 148
_RELATED_COL = 149
_REQ_PAT = re.compile(r"\b(?:Sw|Sy)[A-Za-z_]*_\d+\b")

# 헤더 스캔 범위 — SUTS 템플릿이 2종(레이아웃 상이)이라 위 상수만으론 한쪽만 맞다.
#   HDPDM01 v3.01 : 헤더 rows5-6, SeqNo=13 Input=14.. Expected=63.. Related=149  ← 위 상수와 일치
#   KJPDS02_PV v1.02: 헤더 rows3-4, SeqNo=8  Inpt[0]=9.. ExpR[0]=105.. Related=189
# 하드코딩 상수는 KJPDS02_PV에서 입력컬럼(col13=Inpt[4])을 SeqNo 게이트로 오용 → 입력 ≤4개 함수의
# 전 시퀀스행이 '빈 블록'으로 드롭(1013중 704), 파싱된 것도 입력/기대값이 컬럼 밀림으로 오염됐다.
_HEADER_SCAN_ROWS = 8
_MAX_SCAN_COLS = 1024


def _detect_columns(ws: Any) -> Dict[str, Any]:
    """문서 헤더에서 실제 컬럼 위치를 탐지(레이아웃 적응형). 모듈 상수는 HDPDM01 기본값·폴백.

    불변식(관측된 3개 레이아웃 모두 성립): SeqNo=입력시작-1, 입력끝=출력시작-1, 출력끝=Related-1.
    전역 Input/Inpt[0]/Expected/Related 헤더가 없는 문서(구 단위테스트 픽스처)는 밴드를 탐지하지
    못하므로 모듈 상수를 그대로 유지한다(무회귀). TC_ID(3)/Name(4)은 3개 레이아웃 공통이라 상수 유지.
    ⚠ 'Input' 병합앵커가 KJPDS02_PV에선 SeqNo 컬럼(c8)에 걸리므로 Inpt[0]를 우선 신뢰한다."""
    cols: Dict[str, Any] = {
        "component": _COMPONENT_COL, "tc_id": _TC_ID_COL, "name": _NAME_COL,
        "description": _DESCRIPTION_COL, "test_method": _TEST_METHOD_COL,
        "gen_method": _GEN_METHOD_COL, "precondition": _PRECONDITION_COL,
        "seq_text": _SEQUENCE_TEXT_COL, "tc_gen_method": _TC_GEN_METHOD_COL,
        "seq_no": _SEQ_NO_COL, "input_start": _INPUT_COL_START, "input_end": _INPUT_COL_END,
        "output_start": _OUTPUT_COL_START, "output_end": _OUTPUT_COL_END, "related": _RELATED_COL,
        "data_start": _DATA_START_ROW,
    }
    inpt0 = input_hdr = expected = related = None
    found: Dict[str, int] = {}
    gen_cols: List[int] = []
    tc_header_row = None
    maxc = min(int(ws.max_column or 0), _MAX_SCAN_COLS)
    for r in range(1, _HEADER_SCAN_ROWS + 1):
        for c in range(1, maxc + 1):
            raw = ws.cell(row=r, column=c).value
            if raw is None:
                continue
            t = str(raw).strip().lower()
            if not t:
                continue
            # ⚠ 개행/탭/연속공백을 단일 공백으로 접는다 — generators/suts.py 가 실제로 쓰는 헤더는
            # "Test\nMethod"·"Gen.\nMethod"·"Test Case\nGen.Method" 처럼 **개행 삽입**이라(deep-review C1)
            # strip/replace만으론 라벨이 안 맞아 header_driven 문서에서 test_method/gen_method 를
            # 조용히 None(→"")으로 떨궜다(HDPDM01 생성본 재파싱 시 provenance 침묵 손실).
            tn = " ".join(t.replace("_", " ").split())
            if c == _TC_ID_COL and tn == "tc id" and tc_header_row is None:
                tc_header_row = r
            if inpt0 is None and re.fullmatch(r"(?:inpt|input)\[0\]", tn):
                inpt0 = c
            if input_hdr is None and tn == "input":
                input_hdr = c
            # "expected result"로 좁힌다(W2 오탐 방지) — 스캔창(rows 1-8)이 데이터행과 겹쳐
            # "Expected coverage…" 같은 산문이 bare "expected"에 걸려 output_start를 탈취하던 벡터 차단.
            # 생성기/라이브 2템플릿 모두 헤더는 "Expected Result"(개행은 정규화가 접음).
            if expected is None and tn.startswith("expected result"):
                expected = c
            if related is None and "related id" in tn:
                related = c
            if "description" not in found and tn == "description":
                found["description"] = c
            if "precondition" not in found and tn == "precondition":
                found["precondition"] = c
            if "seq_text" not in found and tn == "sequence":
                found["seq_text"] = c
            if "test_method" not in found and tn == "test method":
                found["test_method"] = c
            # "generation method"(정식) 과 "gen. method"(생성본 약어) 를 모두 포용. 'test method'는
            # 'gen'을 포함하지 않으므로 오탐 없음.
            if "gen" in tn and "method" in tn and c not in gen_cols:
                gen_cols.append(c)
    if gen_cols:
        found["gen_method"] = gen_cols[0]
    input_start = inpt0 or input_hdr
    # 밴드 원자성(W1): input과 expected를 **함께** 탐지해야 밴드를 신뢰한다. input만 탐지하고 상수
    # output/related와 섞으면 역전/혼합 밴드(예 [63..29] 공집합, 입력밴드가 expected 열 흡수)를 만들어
    # expected 값이 input으로 오분류되는 침묵 손상이 난다 → 부분탐지는 전부 상수 폴백(구 파서 동작).
    header_driven = input_start is not None and expected is not None
    if header_driven and tc_header_row is not None:
        # Both reference layouts have a TC_ID header, but start at row 5 or 7.
        # Only trust this anchor together with complete input/output bands.
        header_end = tc_header_row
        for merged in ws.merged_cells.ranges:
            if merged.min_col <= _TC_ID_COL <= merged.max_col and merged.min_row <= tc_header_row <= merged.max_row:
                header_end = max(header_end, merged.max_row)
        cols["data_start"] = header_end + 1
    if input_start is not None and expected is not None:
        cols["input_start"] = input_start
        cols["seq_no"] = input_start - 1
        cols["output_start"] = expected
        cols["input_end"] = expected - 1
        if related is not None:
            cols["related"] = related
            cols["output_end"] = related - 1
    elif input_start is not None:
        # 입력 헤더는 있는데 Expected 헤더가 없다 = 미지/변형 레이아웃. 침묵 손상 대신 사유를 남긴다(X8).
        cols["_detect_warning"] = ("SUTS 헤더탐지: 입력 헤더는 찾았으나 'Expected Result' 미탐지 — "
                                   "상수 레이아웃으로 폴백(밴드 오검출 방지). 컬럼 정합 수동 확인 필요")
    # 필드 컬럼: 라벨을 찾으면 그 컬럼. 못 찾았는데 header_driven이면 그 템플릿에 컬럼이 없는 것
    # (KJPDS02_PV는 Description/Precondition/Sequence-text 부재) → None 반환해 파서가 입력컬럼을
    # 오독(쓰레기값)하는 대신 "" 를 쓰게 한다. header_driven이 아니면(픽스처/부분탐지) 상수 유지.
    for key in ("description", "precondition", "seq_text", "test_method", "gen_method"):
        if key in found:
            cols[key] = found[key]
        elif header_driven:
            cols[key] = None
    cols["tc_gen_method"] = gen_cols[1] if len(gen_cols) >= 2 else (None if header_driven else _TC_GEN_METHOD_COL)
    return cols


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return text


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return None
    if text.startswith("[검증 필요]"):
        return {"verification_required": True, "raw": text}
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except Exception:
            return text
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except Exception:
            return text
    return text


def _extract_related_ids(*texts: str) -> List[str]:
    ids: List[str] = []
    for text in texts:
        for req_id in _REQ_PAT.findall(str(text or "")):
            if req_id not in ids:
                ids.append(req_id)
    return ids


def _iter_tc_blocks(ws: Any, cols: Dict[str, Any]) -> Iterable[Tuple[int, int]]:
    tc_col = cols["tc_id"] or _TC_ID_COL
    row = cols.get("data_start", _DATA_START_ROW)
    max_row = ws.max_row
    while row <= max_row:
        if _clean_text(ws.cell(row=row, column=tc_col).value):
            start = row
            row += 1
            while row <= max_row and not _clean_text(ws.cell(row=row, column=tc_col).value):
                row += 1
            yield start, row - 1
        else:
            row += 1


def _header_names(ws: Any, row: int, col_start: int, col_end: int) -> List[Tuple[int, str]]:
    headers: List[Tuple[int, str]] = []
    for col in range(col_start, col_end + 1):
        name = _clean_text(ws.cell(row=row, column=col).value)
        if name:
            headers.append((col, name))
    return headers


def _parse_sequence_row(
    ws: Any,
    row: int,
    input_headers: List[Tuple[int, str]],
    output_headers: List[Tuple[int, str]],
    unit_meta: Dict[str, Any],
    cols: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    warnings: List[Dict[str, str]] = []
    seq_no = ws.cell(row=row, column=cols["seq_no"] or _SEQ_NO_COL).value
    seq_no_text = _clean_text(seq_no)
    sequence_no = int(seq_no) if isinstance(seq_no, int) else seq_no_text
    base_tc_id = str(unit_meta["base_tc_id"])
    _seq_text_col = cols.get("seq_text")
    sequence = {
        "name": f"{base_tc_id}__SEQ_{int(sequence_no):02d}" if str(sequence_no).isdigit() else f"{base_tc_id}__SEQ_{seq_no_text or row}",
        "base_tc_id": base_tc_id,
        "sequence_no": sequence_no,
        "description": _clean_text(ws.cell(row=row, column=_seq_text_col).value) if _seq_text_col else "",
        "precondition": unit_meta.get("precondition", ""),
        "inputs": {},
        "expected": {},
        "notes": {
            "strategy": unit_meta.get("gen_method", ""),
            "test_method": unit_meta.get("test_method", ""),
        },
    }
    for col, name in input_headers:
        value = _normalize_scalar(ws.cell(row=row, column=col).value)
        if value is not None:
            sequence["inputs"][name] = value
    for col, name in output_headers:
        value = _normalize_scalar(ws.cell(row=row, column=col).value)
        if value is not None:
            sequence["expected"][name] = value
            if isinstance(value, dict) and value.get("verification_required"):
                warnings.append(
                    {
                        "code": "verification_required_expected",
                        "message": f"{unit_meta['unit_name']} seq {sequence_no}: expected '{name}' needs manual verification.",
                    }
                )
    if not sequence["expected"]:
        warnings.append(
            {
                "code": "empty_expected",
                "message": f"{unit_meta['unit_name']} seq {sequence_no}: no expected outputs mapped.",
            }
        )
    return sequence, warnings


def _parse_tc_block(ws: Any, start_row: int, end_row: int, cols: Dict[str, Any]) -> Dict[str, Any]:
    def _cell(key: str, fallback: int) -> str:
        col = cols.get(key)
        col = col if col is not None else fallback
        return _clean_text(ws.cell(row=start_row, column=col).value)

    def _cell_opt(key: str) -> str:
        # header_driven 템플릿에서 부재 컬럼은 None → "" (입력컬럼 오독 방지).
        col = cols.get(key)
        return _clean_text(ws.cell(row=start_row, column=col).value) if col is not None else ""

    component = _cell("component", _COMPONENT_COL)
    tc_id = _cell("tc_id", _TC_ID_COL)
    unit_name = _cell("name", _NAME_COL)
    description = _cell_opt("description")
    precondition = _cell_opt("precondition")
    test_method = _cell_opt("test_method")
    gen_method = _cell_opt("gen_method") or _cell_opt("tc_gen_method")
    related_token = _cell_opt("related")
    # related_token(Related ID/SUDS 컬럼)도 채굴 대상에 포함(deep-review W4) — KJPDS02_PV는
    # Description/Precondition 컬럼이 없어 산문만 쓰면 복구된 1013 유닛이 요구 추적 0이 된다.
    # Related ID 컬럼은 존재하므로 여기서 요구/설계 ID를 뽑아 추적성을 살린다(정규식 게이트=무해).
    related_ids = _extract_related_ids(description, precondition, related_token)
    input_headers = _header_names(ws, start_row, cols["input_start"] or _INPUT_COL_START, cols["input_end"] or _INPUT_COL_END)
    output_headers = _header_names(ws, start_row, cols["output_start"] or _OUTPUT_COL_START, cols["output_end"] or _OUTPUT_COL_END)
    unit = {
        "unit_name": unit_name,
        "prototype": "",
        "component": component,
        "fid": related_token,
        "metadata": {
            "gen_method": gen_method,
            "test_method": test_method,
            "related_ids": related_ids,
        },
        # 이 TC 블록이 실제로 쓰는 Input/Expected 컬럼명(시트 헤더행 원문). 시퀀스 dict의
        # inputs/expected 키와 동일 문자열이며 **시트 열 순서를 보존**한다.
        # 영향도 탭의 문서 초안이 (a) 재계산 대상 변수집합과 (b) Excel 붙여넣기 컬럼 순서를
        # 여기서 얻는다 — 시그니처 파라미터로 유추하면 원문과 다른 변수를 가리키게 된다
        # (실측: 원문은 g_sys_error_his[0..4], 유추는 u16t_Data). VectorCAST 산출에는 무영향.
        "columns": {
            "inputs": [n for _, n in input_headers],
            "expected": [n for _, n in output_headers],
            "sheet": _TC_SHEET,
        },
        "test_cases": [],
        "warnings": [],
    }
    unit_meta = {
        "unit_name": unit_name,
        "base_tc_id": tc_id,
        "precondition": precondition,
        "gen_method": gen_method,
        "test_method": test_method,
    }
    _seq_gate = cols["seq_no"] or _SEQ_NO_COL
    for row in range(start_row + 1, end_row + 1):
        if ws.cell(row=row, column=_seq_gate).value in (None, ""):
            continue
        test_case, warnings = _parse_sequence_row(ws, row, input_headers, output_headers, unit_meta, cols)
        test_case["metadata"] = {
            "related_ids": related_ids,
            "fid": related_token,
            "component": component,
        }
        test_case["source"] = {
            "sheet": _TC_SHEET,
            "tc_row": start_row,
            "sequence_row": row,
        }
        unit["test_cases"].append(test_case)
        unit["warnings"].extend(warnings)
    if not unit["test_cases"]:
        unit["warnings"].append(
            {"code": "empty_test_case_block", "message": f"{unit_name or tc_id}: no sequence rows found."}
        )
    return unit


def bare_fn_name(name: Any) -> str:
    """Extract the bare C identifier from a unit name that may be a full signature.

    SUTS 템플릿에 따라 'Unit Name' 컬럼이 bare 함수명(KJPDS02_PV: 's_sha256_update')이거나
    전체 시그니처(HDPDM01: 'void g_SysOs_WdiCtrl( void )')다. 영향 분석은 SVN diff의 bare
    함수명과 매칭하므로, 시그니처는 반환타입·파라미터를 벗겨 식별자만 남긴다.
    이미 bare면 무변경(idempotent) — KJPDS02_PV 등 bare 템플릿은 영향 없음.
    """
    s = str(name or "").strip()
    if not s:
        return s
    head = s.split("(", 1)[0]              # 파라미터 목록('( void )') 제거
    toks = head.replace("*", " ").split()  # 포인터 반환('*')은 식별자 문자가 아님
    return toks[-1] if toks else s          # 반환타입·한정자(static 등) 뒤 마지막 토큰이 함수명


def _attach_test_evidence(workbook: Any, units: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Join provenance by rendered TC identity; never trust stale numeric evidence."""
    if "Test Evidence" not in workbook.sheetnames:
        return []  # Legacy references have no generated provenance sheet.
    rows = workbook["Test Evidence"].iter_rows(values_only=True)
    headers = list(next(rows, ()))
    required = {"Test Case ID", "Sequence", "Observable", "Expected", "Status", "Oracle", "Execution"}
    index: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    case_names: Dict[Tuple[str, str], List[str]] = {}
    duplicate = set()
    if required.issubset(headers):
        for row in rows:
            item = dict(zip(headers, row, strict=False))
            key = tuple(_clean_text(item.get(k)) for k in ("Test Case ID", "Sequence", "Observable"))
            if key in index:
                duplicate.add(key)
            else:
                case_names.setdefault(key[:2], []).append(key[2])
            index[key] = item
    counts: Dict[str, int] = {}
    for unit in units:
        for case in unit.get("test_cases") or []:
            tc, seq = _clean_text(case.get("base_tc_id")), _clean_text(case.get("sequence_no"))
            existing = case.get("expected") or {}
            names = list(dict.fromkeys([*existing, *case_names.get((tc, seq), [])]))
            evidence = {}
            for name in names:
                key = (tc, seq, name)
                item = index.get(key)
                reason = ""
                if item is None:
                    reason = "missing_expected_evidence"
                elif key in duplicate:
                    reason = "ambiguous_expected_evidence"
                elif _normalize_scalar(item.get("Expected")) != existing.get(name):
                    reason = "stale_expected_evidence"
                if not reason:
                    try:
                        saved_inputs = json.loads(_clean_text(item.get("Inputs JSON")))
                    except (ValueError, TypeError):
                        saved_inputs = None
                    if not isinstance(saved_inputs, dict):
                        reason = "missing_input_evidence"
                    elif {k: _normalize_scalar(v) for k, v in saved_inputs.items()} != (case.get("inputs") or {}):
                        reason = "stale_input_evidence"
                    elif _clean_text(item.get("Function")) != bare_fn_name(unit.get("unit_name", "")):
                        reason = "stale_function_evidence"
                status = _clean_text(item.get("Status")) if item else "unrecorded"
                oracle = _clean_text(item.get("Oracle")) if item else "none"
                if not reason and oracle != {"derived": "source", "unknown": "none",
                                             "proposed": "ai", "unrecorded": "none"}.get(status):
                    reason = "invalid_expected_evidence"
                source_hash = _clean_text(item.get("Source SHA256")) if item else ""
                if not reason and status == "derived" and not re.fullmatch(r"[a-f0-9]{64}", source_hash):
                    reason = "missing_source_hash"
                if reason:
                    status, oracle = "conflict", "none"
                    if name in existing:
                        existing[name] = {"verification_required": True, "raw": f"[검증 필요] {reason}"}
                    counts[reason] = counts.get(reason, 0) + 1
                elif status == "derived":
                    counts["source_oracle_requires_requirement_review"] = counts.get("source_oracle_requires_requirement_review", 0) + 1
                elif name in existing and not (isinstance(existing[name], dict)
                                               and existing[name].get("verification_required")):
                    existing[name] = {"verification_required": True, "raw": "[검증 필요] unproven_expected_evidence"}
                    counts["unproven_expected_evidence"] = counts.get("unproven_expected_evidence", 0) + 1
                evidence[name] = {
                    "status": status, "oracle_kind": oracle,
                    "source_hash": source_hash,
                    "source_path": _clean_text(item.get("Source path")) if item else "",
                    "source_hash_scope": _clean_text(item.get("Source hash scope")) if item else "",
                    "reason": reason or _clean_text(item.get("Reason")),
                    "execution_status": "not_run", "requirement_verified": False,
                }
            case["expected_evidence"] = evidence
            case["execution_status"] = "not_run"
    return [{"code": code, "message": f"{code}: {count} expected slots; review provenance before execution."}
            for code, count in sorted(counts.items())]


def _attach_mcdc_design(workbook: Any, units: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Preserve design evidence without promoting worksheet claims to coverage.

    Input identity is checked here; the original source and target instrumentation
    are unavailable at import, so even consistent rows require revalidation.
    """
    if "MCDC Design" not in workbook.sheetnames:
        return []
    rows = workbook["MCDC Design"].iter_rows(values_only=True)
    headers = list(next(rows, ()))
    required = {"Test Case ID", "Function", "Decision ID", "Pair ID", "Sequence A",
                "Sequence B", "Inputs A JSON", "Inputs B JSON"}
    if not required.issubset(headers):
        return [{"code": "invalid_mcdc_design_schema", "message": "MC/DC design requires source revalidation."}]
    by_tc: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        item = dict(zip(headers, row, strict=False))
        by_tc.setdefault(_clean_text(item.get("Test Case ID")), []).append(item)
    conflicts = not_retained = 0
    for unit in units:
        cases = unit.get("test_cases") or []
        case_counts = Counter((_clean_text(c.get("base_tc_id")), _clean_text(c.get("sequence_no"))) for c in cases)
        case_index = {(_clean_text(c.get("base_tc_id")), _clean_text(c.get("sequence_no"))): c for c in cases}
        evidence = []
        for tc in dict.fromkeys(key[0] for key in case_index):
            items = by_tc.get(tc, [])
            identities = [(_clean_text(i.get("Decision ID")), _clean_text(i.get("Pair ID")),
                           _clean_text(i.get("Condition ID"))) for i in items]
            identity_counts = Counter(identities)
            for item, identity in zip(items, identities, strict=True):
                reason = ""
                if identity_counts[identity] != 1:
                    reason = "duplicate_mcdc_design"
                elif _clean_text(item.get("Function")) != bare_fn_name(unit.get("unit_name", "")):
                    reason = "stale_mcdc_function"
                elif identity[1] and _clean_text(item.get("Retained")) in ("truncated", "invalidated"):
                    # 생성기가 이미 "행 상한/재검증에서 탈락" 이라 적은 쌍 — 충돌이 아니라 **미보유**다. 커버리지 주장 없이 싣는다.
                    not_retained += 1
                    evidence.append({"worksheet_evidence": item, "verification_status": "not_retained",
                                     "reason": f"mcdc_pair_{_clean_text(item.get('Retained'))}",
                                     "execution_status": "not_run", "executed_mcdc_coverage": None})
                    continue
                elif identity[1]:
                    for side in ("A", "B"):
                        case_key = (tc, _clean_text(item.get(f"Sequence {side}")))
                        case = case_index.get(case_key)
                        if case_counts[case_key] > 1:
                            reason = "ambiguous_mcdc_sequence"
                            break
                        try:
                            saved = json.loads(_clean_text(item.get(f"Inputs {side} JSON")))
                        except (TypeError, ValueError):
                            saved = None
                        if case is None or not isinstance(saved, dict):
                            reason = "missing_mcdc_pair_input"
                            break
                        if {k: _normalize_scalar(v) for k, v in saved.items()} != (case.get("inputs") or {}):
                            reason = "stale_mcdc_pair_input"
                            break
                conflicts += bool(reason)
                evidence.append({"worksheet_evidence": item, "verification_status": "conflict" if reason else "source_revalidation_required",
                                 "reason": reason or "imported_design_is_not_execution_coverage",
                                 "execution_status": "not_run", "executed_mcdc_coverage": None})
        unit["mcdc_design_evidence"] = evidence
    return [{"code": "mcdc_design_requires_revalidation",
             "message": f"Imported MC/DC design is not measured coverage; {conflicts} conflicting rows, "
                        f"{not_retained} pairs not retained by the generator (truncated/invalidated)."}]


def build_vectorcast_model(
    suts_path: str,
    *,
    project_id: str = "HDPDM01",
    target_functions: Optional[Iterable[str]] = None,
    source_bytes: Optional[bytes] = None,
) -> Dict[str, Any]:
    target_set = {str(x or "").strip().lower() for x in (target_functions or []) if str(x or "").strip()}
    # cloudium(U:\)에서는 backend가 파일을 직접 열 수 없어 workbook을 worker가 읽은 bytes로 받는다.
    # source_bytes가 주어지면 그 bytes로, 아니면 로컬 경로에서 연다(로컬 모드 하위호환).
    if source_bytes is not None:
        import io as _io
        workbook = load_workbook(_io.BytesIO(source_bytes), keep_vba=True, data_only=False)
    else:
        workbook = load_workbook(suts_path, keep_vba=True, data_only=False)
    if _TC_SHEET not in workbook.sheetnames:
        raise ValueError(f"missing worksheet: {_TC_SHEET}")
    ws = workbook[_TC_SHEET]
    cols = _detect_columns(ws)
    units: List[Dict[str, Any]] = []
    export_warnings: List[Dict[str, str]] = []
    _detect_warn = cols.pop("_detect_warning", None)
    if _detect_warn:
        export_warnings.append({"code": "header_detect_fallback", "message": str(_detect_warn)})
    for start_row, end_row in _iter_tc_blocks(ws, cols):
        unit = _parse_tc_block(ws, start_row, end_row, cols)
        # unit_name은 템플릿에 따라 bare(KJPDS02_PV) 또는 시그니처(HDPDM01 'void f( void )')다.
        # target(=영향 함수)은 SVN diff의 bare 이름이므로 raw·bare 양쪽으로 매칭한다 — 시그니처
        # 템플릿에서 전 유닛이 침묵 필터링돼 회귀 TC/문서카드가 0이 되던 것 차단(superset=무회귀).
        if target_set:
            _un = unit["unit_name"].strip().lower()
            if _un not in target_set and bare_fn_name(_un) not in target_set:
                continue
        if not unit["unit_name"]:
            export_warnings.append(
                {"code": "missing_unit_name", "message": f"TC row {start_row}: unit name is empty."}
            )
        if unit["warnings"]:
            export_warnings.extend(unit["warnings"])
        units.append(unit)
    export_warnings.extend(_attach_test_evidence(workbook, units))
    export_warnings.extend(_attach_mcdc_design(workbook, units))
    workbook.close()
    return {
        "schema_version": "1.0",
        "project_id": project_id,
        "source": {
            "suts_path": str(suts_path) if source_bytes is not None else str(Path(suts_path).resolve()),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "units": units,
        "export_warnings": export_warnings,
    }


def write_warnings_md(model: Dict[str, Any], out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    warnings = list(model.get("export_warnings") or [])
    lines = [
        "# SUTS -> VectorCAST Export Warnings",
        "",
        f"- Units: `{len(model.get('units') or [])}`",
        f"- Warnings: `{len(warnings)}`",
        "",
    ]
    if not warnings:
        lines.append("- none")
    else:
        for item in warnings:
            lines.append(f"- `{item.get('code')}`: {item.get('message')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_suts_to_vectorcast_model(
    suts_path: str,
    output_json: str,
    *,
    warnings_md: str = "",
    target_functions: Optional[Iterable[str]] = None,
    project_id: str = "HDPDM01",
) -> Dict[str, Any]:
    model = build_vectorcast_model(
        suts_path,
        project_id=project_id,
        target_functions=target_functions,
    )
    out_path = Path(output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    if warnings_md:
        write_warnings_md(model, warnings_md)
    return model


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export SUTS XLSM to VectorCAST intermediate JSON.")
    parser.add_argument("--suts-path", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--warnings-md", default="")
    parser.add_argument("--target-functions", default="")
    parser.add_argument("--project-id", default="HDPDM01")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    targets = [x.strip() for x in str(args.target_functions or "").split(",") if x.strip()]
    model = export_suts_to_vectorcast_model(
        args.suts_path,
        args.output_json,
        warnings_md=args.warnings_md,
        target_functions=targets,
        project_id=args.project_id,
    )
    print(f"VECTORCAST_JSON={Path(args.output_json).resolve()}")
    print(f"VECTORCAST_UNITS={len(model.get('units') or [])}")
    print(f"VECTORCAST_WARNINGS={len(model.get('export_warnings') or [])}")
    if args.warnings_md:
        print(f"VECTORCAST_WARNINGS_MD={Path(args.warnings_md).resolve()}")


if __name__ == "__main__":
    main()
