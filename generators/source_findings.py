"""Source findings (R10) — defect candidates the source oracle already proved while deriving expected values.

A SUTS sequence whose expected value the oracle could not derive because **a run of the function is undefined** (C11:
a signed result outside its type, a division by zero, a shift out of range) records that as its reason
(``undefined_behavior:<kind>``). That is a statement about the source: *with these inputs, at least one execution path
of the function has undefined behaviour* — possibly a path behind a condition the inputs leave open (review round 1
W5), so it is not a proof that every run fails. A reference test specification carries none of this; here it becomes a
"Source Findings" sheet, one row per (function, kind), with the sequences it occurred in, an example vector, and the
expected-value slots it blocked (a UB refuses the whole run, so unrelated outputs of that sequence count as blocked —
the sequence count is the measure, review W4).

A finding is a **candidate**: the example inputs may lie outside what the callers can produce (a type-maximum boundary
row). Each row says so, and says whether it was reproduced independently — the generator does not run clang
(`scripts/source_findings.py --clang` re-evaluates every example with clang constant evaluation and reports whether
clang stops on undefined behaviour of that kind).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

FINDINGS_SHEET = "Source Findings"
FINDINGS_HEADERS = ["Function ID", "Function", "Kind", "Sequences", "Blocked Expected Slots", "Observables",
                    "Example Test Case ID", "Example Sequence", "Example Inputs JSON", "Source path", "Source SHA256",
                    "Meaning", "Reproduction"]
_UB = re.compile(r"undefined_behavior:([a-z_]+)")
_ON_A_PATH = "이 입력에서 적어도 한 실행 경로(입력이 정하지 않은 조건의 분기 포함)가 "
MEANING = {
    "signed_overflow": _ON_A_PATH + "부호 있는 산술 결과를 형 범위 밖으로 낸다(C 미정의 동작). 호출 측이 이 값을 막는다는 "
                       "근거가 없으면 결함 후보 — 입력 도메인 제약이나 포화 처리를 확인할 것",
    "division_by_zero": _ON_A_PATH + "0 으로 나눈다(C 미정의 동작). 제수가 0 이 될 수 없다는 근거가 없으면 결함 후보 — "
                        "0 검사를 확인할 것",
    "shift_count_out_of_range": _ON_A_PATH + "형 폭 이상으로 시프트한다(C 미정의 동작) — 시프트 수 범위를 확인할 것",
    "signed_left_shift_overflow": _ON_A_PATH + "부호 있는 값을 왼쪽 시프트해 범위를 넘긴다(C 미정의 동작)",
    "float_to_int_out_of_range": _ON_A_PATH + "정수형이 담을 수 없는 실수를 정수로 바꾼다(C 미정의 동작)",
    "array_index_out_of_bounds": _ON_A_PATH + "배열 범위 밖을 읽거나 쓴다(C 미정의 동작) — 첨자 범위 검사를 확인할 것",
}
NOT_REPRODUCED_HERE = "not_run (clang 재현: scripts/source_findings.py --clang)"
# (R19) 입력 목록 밖 읽기 — 미정의 동작이 아니라 **시험 명세의 입력 목록**에 대한 소견이다(clang 재현 대상 아님).
INPUT_GAP_KIND = "read_not_in_unit_inputs"
MEANING[INPUT_GAP_KIND] = (
    "함수가 이 객체의 초기값을 읽는데(이 입력으로 돌리면 쓰기 전에 읽는다 — oracle 사유 `initial_value_not_in_inputs`) 시험 입력 "
    "목록(설계서 입력 표·소스 분석)에 없다. 설계서 입력 누락 또는 입력으로 적지 않은 내부 상태 후보 — 설계서의 입력 표를 확인할 것. "
    "확장 프로파일은 이 객체들을 선언 타입으로 입력 열에 더했다")
INPUT_GAP_REPRODUCTION = "해당 없음 — 입력 목록 대조(clang 재현 대상 아님)"


def collect_findings(units: list[dict[str, Any]], all_sequences: dict[str, list[dict[str, Any]]],
                     rendered_tc_ids: dict[str, str]) -> list[dict[str, Any]]:
    """One finding per (function, UB kind) over every expected slot whose reason is proven undefined behaviour."""
    found: dict[tuple, dict[str, Any]] = {}
    for unit in units:
        for seq in all_sequences.get(unit["fid"], []):
            for var, ev in (seq.get("expected_evidence") or {}).items():
                m = _UB.search(str((ev or {}).get("reason") or ""))
                if not m:
                    continue
                key = (unit["fid"], m.group(1))
                f = found.setdefault(key, {
                    "function_id": unit["fid"], "function": unit.get("name", ""), "kind": m.group(1),
                    "occurrences": 0, "sequences": [], "observables": [],
                    "example_tc": rendered_tc_ids.get(unit["fid"], ""),
                    "example_sequence": seq.get("seq_num"), "example_inputs": dict(seq.get("inputs") or {}),
                    "example_observable": var, "source_path": (ev or {}).get("source_path", ""),
                    "source_hash": (ev or {}).get("source_hash", "")})
                f["occurrences"] += 1
                if seq.get("seq_num") not in f["sequences"]:
                    f["sequences"].append(seq.get("seq_num"))
                if var not in f["observables"]:
                    f["observables"].append(var)
    return sorted(found.values(), key=lambda f: (f["function"], f["kind"]))


def collect_input_gap_findings(units: list[dict[str, Any]], gaps: dict[str, dict[str, dict[str, Any]]],
                               rendered_tc_ids: dict[str, str]) -> list[dict[str, Any]]:
    """(R19) unit 마다 한 행 — 함수가 초기값을 읽는데 시험 입력 목록에 없던 프로그램 객체(`gaps[fid]` = 이름 → {"slots",
    "sequences"}; `generators.suts.input_list_gaps` 가 만든다). 확장 프로파일에선 그 이름들이 이미 입력 열로 더해져 있다."""
    out = []
    for unit in units:
        names = gaps.get(unit["fid"]) or {}
        if not names:
            continue
        seqs = sorted({s for g in names.values() for s in (g.get("sequences") or []) if s is not None})
        out.append({"function_id": unit["fid"], "function": unit.get("name", ""), "kind": INPUT_GAP_KIND,
                    "occurrences": sum(int(g.get("slots") or 0) for g in names.values()), "sequences": seqs,
                    "observables": sorted(names, key=lambda n: (-int(names[n].get("slots") or 0), n)),
                    "example_tc": rendered_tc_ids.get(unit["fid"], ""), "example_sequence": seqs[0] if seqs else None,
                    "example_inputs": {}, "source_path": unit.get("source_path", ""),
                    "source_hash": str((unit.get("project_scope") or {}).get("main_file_sha256") or "")})
    return sorted(out, key=lambda f: f["function"])


def summarize_input_gaps(findings: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = [f for f in findings if f["kind"] == INPUT_GAP_KIND]
    return {"functions": len(gaps), "names": sum(len(f["observables"]) for f in gaps),
            "slots": sum(f["occurrences"] for f in gaps)}


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {"findings": len(findings), "by_kind": dict(Counter(f["kind"] for f in findings)),
            "functions": len({f["function_id"] for f in findings}),
            "sequences": sum(len(f["sequences"]) for f in findings),
            "blocked_expected_slots": sum(f["occurrences"] for f in findings), "reproduction": "not_run"}


def write_source_findings_sheet(wb, findings: list[dict[str, Any]], hdr_font=None, hdr_fill=None, border=None) -> int:
    """'Source Findings' sheet (replaces one of that name). No findings → no sheet (and an old one is removed)."""
    if FINDINGS_SHEET in wb.sheetnames:
        del wb[FINDINGS_SHEET]
    if not findings:
        return 0
    ws = wb.create_sheet(FINDINGS_SHEET)
    ws.append(FINDINGS_HEADERS)
    for cell in ws[1]:
        if hdr_font is not None:
            cell.font = hdr_font
        if hdr_fill is not None:
            cell.fill = hdr_fill
        if border is not None:
            cell.border = border
    ws.freeze_panes = "A2"
    for f in findings:
        ws.append([f["function_id"], f["function"], f["kind"], len(f["sequences"]), f["occurrences"],
                   ", ".join(f["observables"][:12]), f["example_tc"], f["example_sequence"],
                   json.dumps(f["example_inputs"], ensure_ascii=False, sort_keys=True), f["source_path"],
                   f["source_hash"], MEANING.get(f["kind"], "C 미정의 동작 — 결함 후보"),
                   INPUT_GAP_REPRODUCTION if f["kind"] == INPUT_GAP_KIND else NOT_REPRODUCED_HERE])
    for col, width in zip("ABCDEFGHIJKLM", (14, 30, 18, 10, 12, 40, 22, 10, 60, 48, 20, 70, 36), strict=True):
        ws.column_dimensions[col].width = width
    return len(findings)
