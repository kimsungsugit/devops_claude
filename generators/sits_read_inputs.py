"""SITS 행이 쓰는 입력 — 문서에 보이게 하기(S0)와, 소스가 읽는 입력으로 열을 채울 계획(S2, 아직 생성에 배선하지 않음).

## S0 — 숨은 입력을 열로 (SUTS R21 `suts.render_row_io` 의 SITS 판)

GLOBAL 행(`sits._generate_sub_case_candidates` 의 GAP D)은 간접 전역 ``gv`` 를 입력으로 최솟값에 두고 기대값으로도 적는데, 명세 시트는
TC 의 ``input_vars`` · ``expected_vars`` 열만 쓴다. 그 이름이 열에 없으면 통합 oracle 은 **문서에 없는 자극**으로 기대값을 도출한다
(HDPDM01 SwITC_94/96/97 `u8g_SysUds_WriteData` · `u8g_SysUds_WdbiCmd`). `render_hidden_inputs` 가 oracle **전에** 그 이름을 첫 사용
순서로 기존 열 **뒤에** 붙인다(기존 열 이름 · 위치 · 값은 그대로 — R75). 입력 열 상한(82)에 막혀 붙이지 못한 입력을 쓰는 행에는 표시를
남기고, oracle 이 끝난 뒤 `downgrade_hidden_input_rows` 가 그 행의 확정 칸을 `[검증 필요] input_not_in_document:<이름>` 으로 내린다
(oracle 파일은 이 단계에서 고치지 않으므로 **후처리**다 — 통합 oracle 통계도 같은 자리에서 맞춘다). 기대값은 상한을 넘으면 열로 보이지
않을 뿐(단언하지 않음) 센다 — SUTS 와 같은 규칙. 지금 생성기에서 숨은 이름을 만드는 행은 GLOBAL 행뿐이지만(입출력 없는 흐름의
`Scenario` · `Result` 는 일반 · FI TC 모두 `sits._effective_io_columns` 가 먼저 열로 낸다) 규칙은 행의 종류를 보지 않는다.

불변식(문서): 렌더 뒤 모든 행의 입력 이름(Test Evidence 시트의 Inputs JSON 키) ⊆ TC 의 입력 열 — **단** `ROW_MARK` 가 붙은 행은 예외이고,
그 행의 열 밖 이름은 정확히 표시된 이름이며 그 행의 확정 칸은 남지 않는다(`downgrade_hidden_input_rows`). 기대 이름 ⊆ 기대 열 ∪ 상한
초과로 기록한 이름(`expected_over_cap`).

## S2 — 소스가 읽는 입력의 계획 (순수 함수, S3 에서 배선)

oracle 이 칸을 막은 사유(`expected_evidence[*].reason`)에서 **값이 없어 막힌 이름**을 모으고(`needed_inputs`), 열로 올릴 수 없는 이름을
사유와 함께 거르고(`exclude_needed`), 순위를 매기고(`rank_needed`), 값을 한 번 정한다(`select_values` — 도메인은 흐름 수집과 같은
`sits._input_domain_resolver`, 값은 EC4 가운데 값에서 `boundary_rows.blank_fill`). 아무것도 생성에 쓰지 않는다.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from generators.test_evidence import DERIVATION_FIELDS, VERIFY_PREFIX

# ── S0 ────────────────────────────────────────────────────────────────────────────────────────────────────────────

#: 내린 칸의 사유 접두 — SUTS `render_row_io` 와 같은 문자열(두 문서의 사유 어휘가 갈라지지 않게)
INPUT_NOT_IN_DOCUMENT = "input_not_in_document:"
#: 행 표시 — 이 행이 쓰는 입력 중 열 상한에 막혀 문서에 없는 이름(첫 사용 순서)
ROW_MARK = "inputs_not_in_document"
#: TC 기록
RECORD_KEY = "hidden_io_columns"

#: 확정 근거 필드 — 내린 칸은 근거를 말하지 않는다(`suts.render_row_io` 리뷰 I1 과 같은 이유). 목록의 단일 출처는
#: `test_evidence.DERIVATION_FIELDS`(필드를 다는 모듈) — R93 통합 때 사본 둘이 레지스터 모델 필드를 빠뜨린 채 갈라졌다.

#: (R93) 위 근거 필드 중 `integration_oracle.attach_integration_evidence` 가 확정 칸마다 센 통계 — 내린 칸은 여기서도 뺀다.
#: 통계 키는 그 근거가 한 칸이라도 있을 때만 생기므로(``stats.get(k, 0) + 1``) 없는 키는 만들지 않는다.
_DERIVATION_COUNTERS: Tuple[Tuple[str, str], ...] = (
    ("polling_loops_assumed", "derived_on_assumed_polling_exit"),
    ("storage_objects", "derived_on_storage_model"),
    ("storage_registers", "derived_on_register_memory"),
    # (callee contract G5 / G6)
    ("callee_termination_assumed", "derived_on_assumed_callee_termination"),
    ("callee_ub_unanalysed", "derived_with_callee_ub_unanalysed"))


def _caps(input_cap: Optional[int], expected_cap: Optional[int]) -> Tuple[int, int]:
    if input_cap is None or expected_cap is None:
        # 열 상한의 단일 출처(시트 배치 상수)
        from generators.sits import _MAX_EXP_PARAMS, _MAX_INPUT_PARAMS
        input_cap = _MAX_INPUT_PARAMS if input_cap is None else input_cap
        expected_cap = _MAX_EXP_PARAMS if expected_cap is None else expected_cap
    return int(input_cap), int(expected_cap)


def render_hidden_inputs(itc: Dict[str, Any], input_cap: Optional[int] = None,
                         expected_cap: Optional[int] = None) -> Dict[str, Any]:
    """(S0) 행이 설정하는 입력 · 적는 기대값인데 TC 의 열에 없는 이름을 열로 보인다. **통합 oracle 전에** 부른다.

    첫 사용 순서(행 순서 · 행 안의 이름 순서)로 기존 열 **뒤에** 붙인다 — 기존 열은 그대로다(R75). 상한(입력 82 · 기대 113, 시트 배치
    상수)을 넘는 입력은 붙이지 않고, 그 입력을 쓰는 행에 `ROW_MARK` 를 남긴다(oracle 뒤 `downgrade_hidden_input_rows` 가 그 행의 확정
    칸을 내린다). 넘는 기대값은 열로 보이지 않을 뿐 센다. 두 번 불려도 앞의 기록(이미 붙인 이름)을 잃지 않는다.
    기록은 ``itc[RECORD_KEY]`` = ``{"inputs_shown", "inputs_over_cap", "expected_shown", "expected_over_cap",
    "rows_input_not_in_document", "downgraded_cells"}``.
    """
    in_cap, exp_cap = _caps(input_cap, expected_cap)
    prev = itc.get(RECORD_KEY) if isinstance(itc.get(RECORD_KEY), dict) else {}
    subs = [sc for sc in (itc.get("sub_cases") or []) if isinstance(sc, dict)]
    record: Dict[str, Any] = {"inputs_shown": [], "inputs_over_cap": [], "expected_shown": [], "expected_over_cap": [],
                              "rows_input_not_in_document": 0,
                              "downgraded_cells": int(prev.get("downgraded_cells") or 0)}
    for cols_key, field, cap, label in (("input_vars", "inputs", in_cap, "inputs"),
                                        ("expected_vars", "expected", exp_cap, "expected")):
        cols = list(itc.get(cols_key) or [])
        known = set(cols)
        hidden: List[str] = []
        for sc in subs:
            for name in (sc.get(field) or {}):
                if name not in known and name not in hidden:
                    hidden.append(name)
        room = max(0, cap - len(cols))
        if hidden[:room]:
            itc[cols_key] = cols + hidden[:room]
        record[f"{label}_shown"] = list(prev.get(f"{label}_shown") or []) + hidden[:room]
        record[f"{label}_over_cap"] = hidden[room:]
    over = set(record["inputs_over_cap"])
    for sc in subs:
        used = [n for n in (sc.get("inputs") or {}) if n in over]
        if used:
            sc[ROW_MARK] = used
            record["rows_input_not_in_document"] += 1
        else:
            sc.pop(ROW_MARK, None)   # 앞 회차의 표시는 이 회차의 것이 아니다
    itc[RECORD_KEY] = record
    return record


def _rewrite_expected_line(seq: Dict[str, Any]) -> None:
    # 설명 줄 규칙의 단일 출처(SUTS 와 같은 줄)
    from generators.suts import _rewrite_expected_line as rewrite
    rewrite(seq)


def downgrade_hidden_input_rows(itcs: List[Dict[str, Any]],
                                oracle_stats: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """(S0) 통합 oracle **뒤** 후처리 — `ROW_MARK` 행의 확정 칸을 `[검증 필요] input_not_in_document:<이름>` 으로 내린다.

    문서에 없는 자극(열 상한에 막힌 입력)에 기댄 값은 확정이 아니다. 근거 필드(`DERIVATION_FIELDS`)를 떼고 status `unknown`.

    ``oracle_stats`` (`integration_oracle.attach_integration_evidence` 의 반환, status ``evaluated``)를 주면 **같은 자리에서** 맞춘다
    — 그 통계는 oracle 이 끝난 시점의 칸을 센 것이라 이 후처리를 모른다:
      * ``derived`` · ``derived_assigned`` / ``derived_unchanged_input``(근거별) · ``derived_with_possible_ub_on_forked_path`` 에서
        내린 칸을 뺀다(``cells`` 는 그대로 — 칸은 남고 미상이 된다). (R93) 저장소 모델 · 레지스터 메모리 · 폴링 종료 가정
        통계(`_DERIVATION_COUNTERS`)도 그 근거가 붙어 있던 내린 칸만큼 뺀다(키가 있을 때만).
      * ``unknown_reasons`` 에 ``input_not_in_document`` 를 더하고 상위 12 를 다시 고른다(oracle 과 같은 상위 12 규칙 —
        새 사유라 상위 12 밖에 이미 있었을 수 없으므로 정확하다). 새 사유면 ``unknown_reason_kinds`` + 1.
      * ``tc_with_derived`` — 확정 칸이 있던 TC 가 이 후처리로 하나도 없게 되면 뺀다. oracle 이 예외로 끝난 TC 는 원래 세지 않으므로
        그런 TC 를 빼면 과하게 빼는 것인데, `generate_sits` 경로에서는 **일어나지 않는다**: oracle 은 TC 마다 앞 `_BUDGET_PROBE`(2)행을
        먼저 돌리고 나머지를 따로 돌린다. 표시가 붙는 행은 GLOBAL 행뿐이고 GLOBAL 행은 서브케이스 상한이 경계값 행 수(7)보다 클 때만 생겨
경계값 행 7개 뒤(8번째 이후)에 온다 —
        나머지 묶음에서 예외가 나면 그 묶음은 아무 칸도 쓰지 않으므로(결과를 다 낸 뒤 쓴다) 표시 행에 확정 칸이 없고, 앞 두 행(표시 없음)의
        확정 칸은 남아 "모두 잃음" 이 되지 않는다. 직접 만든 ITC 로 부르는 호출자를 위해 0 아래로는 내리지 않는다.
      * 무엇을 뺐는지 ``oracle_stats["hidden_input_downgrade"]`` 에 남긴다.
    status 가 ``evaluated`` 가 아니면(도출 안 함 · 실패) 통계는 그대로 두고 칸만 내린다.
    """
    n_cells = n_assigned = n_unchanged = n_ub = tc_lost = 0
    n_counters = {stat: 0 for _field, stat in _DERIVATION_COUNTERS}
    for itc in itcs or []:
        subs = [sc for sc in (itc.get("sub_cases") or []) if isinstance(sc, dict)]
        if not any(sc.get(ROW_MARK) for sc in subs):
            continue

        def _has_derived() -> bool:
            return any((ev or {}).get("status") == "derived"
                       for sc in subs for ev in (sc.get("expected_evidence") or {}).values())

        had = _has_derived()
        here = 0
        for sc in subs:
            used = list(sc.get(ROW_MARK) or [])
            if not used:
                continue
            reason = INPUT_NOT_IN_DOCUMENT + ",".join(used[:3]) + (f"+{len(used) - 3}" if len(used) > 3 else "")
            touched = False
            for var, ev in (sc.get("expected_evidence") or {}).items():
                if not isinstance(ev, dict) or ev.get("status") != "derived":
                    continue
                if var in (sc.get("expected") or {}):   # oracle 통계가 세는 칸(`attach_integration_evidence`)
                    n_cells += 1
                    if ev.get("basis") == "unchanged_input":
                        n_unchanged += 1
                    else:
                        n_assigned += 1
                    n_ub += 1 if ev.get("possible_ub_on_forked_path") else 0
                    for field, stat in _DERIVATION_COUNTERS:
                        n_counters[stat] += 1 if ev.get(field) else 0
                for k in DERIVATION_FIELDS:
                    ev.pop(k, None)
                ev.update(status="unknown", oracle_kind="none", reason=reason)
                sc.setdefault("expected", {})[var] = f"{VERIFY_PREFIX} {reason}"
                here += 1
                touched = True
            if touched:
                _rewrite_expected_line(sc)
        rec = itc.get(RECORD_KEY)
        if isinstance(rec, dict):
            rec["downgraded_cells"] = int(rec.get("downgraded_cells") or 0) + here
        if had and not _has_derived():
            tc_lost += 1
    summary = {"cells": n_cells, "derived_assigned": n_assigned, "derived_unchanged_input": n_unchanged,
               "derived_with_possible_ub_on_forked_path": n_ub, "tc_with_derived": tc_lost,
               **{stat: n for stat, n in n_counters.items() if n}}
    if isinstance(oracle_stats, dict) and oracle_stats.get("status") == "evaluated" and n_cells:
        for key in ("derived", "derived_assigned", "derived_unchanged_input", "derived_with_possible_ub_on_forked_path"):
            sub = n_cells if key == "derived" else summary[key]
            oracle_stats[key] = max(0, int(oracle_stats.get(key) or 0) - sub)
        oracle_stats["tc_with_derived"] = max(0, int(oracle_stats.get("tc_with_derived") or 0) - tc_lost)
        for stat, sub in n_counters.items():
            if sub and stat in oracle_stats:
                oracle_stats[stat] = max(0, int(oracle_stats.get(stat) or 0) - sub)
        reasons = dict(oracle_stats.get("unknown_reasons") or {})
        key = INPUT_NOT_IN_DOCUMENT[:-1]
        if key not in reasons:
            oracle_stats["unknown_reason_kinds"] = int(oracle_stats.get("unknown_reason_kinds") or 0) + 1
        reasons[key] = int(reasons.get(key) or 0) + n_cells
        oracle_stats["unknown_reasons"] = dict(sorted(reasons.items(), key=lambda kv: -int(kv[1] or 0))[:12])
        oracle_stats["hidden_input_downgrade"] = dict(summary)
    return summary


def reconcile_candidate_cuts(itcs: List[Dict[str, Any]], input_axes: Sequence[str], expected_axes: Sequence[str],
                             all_axes: Sequence[str]) -> Dict[str, int]:
    """(S0 리뷰 W1) 렌더 **뒤** — 앞부분 상한에 잘렸다고 센 이름 중 S0 가 열로 보인 것을 TC 의 ``candidate_cuts`` 에서 뺀다.

    흐름 수집은 잘린 이름이 다른 경로로 **관측 후보**가 됐는지만 본다. 그런데 진입 전역(상한 없이)과 callee 전역 앞 5개는 간접 전역
    경로로 GLOBAL 행의 입력 · 기대값이 되고, `render_hidden_inputs` 가 그 이름을 열로 보인다 — 잃은 이름이 아니다(빼지 않으면 한
    이름이 "잃음" 과 "보임" 에 같이 세어져 공시 · 영향도 카드 `flow_*_truncated` · 평가기 지표가 부풀었다). 입력 축(``input_axes``)은
    ``inputs_shown``, 기대 축(``expected_axes``)은 ``expected_shown`` 과 맞춘다. 예산 축(`budget_*`)은 맞추지 않는다 — 예산에 잘린
    흐름은 그 열이 이미 상한까지 차 있어 S0 가 붙일 자리가 없다.

    돌려주는 값은 흐름 단위 합계 ``{"<축>_truncated": n}``(``all_axes`` 전부) — 전용 FI TC(``fi_design_id``)는 같은 흐름의 일반
    TC 가 이미 세므로 넣지 않는다. TC 의 축 목록은 새 리스트로 바꾼다(흐름 · 다른 TC 와 공유하는 리스트를 고치지 않는다).
    """
    totals = {f"{ax}_truncated": 0 for ax in all_axes}
    for itc in itcs or []:
        cuts = itc.get("candidate_cuts")
        if not isinstance(cuts, dict):
            continue
        rec = itc.get(RECORD_KEY) if isinstance(itc.get(RECORD_KEY), dict) else {}
        for axes, shown in ((input_axes, set(rec.get("inputs_shown") or [])),
                            (expected_axes, set(rec.get("expected_shown") or []))):
            for ax in axes:
                if shown and cuts.get(ax):
                    cuts[ax] = [n for n in cuts[ax] if n not in shown]
        if itc.get("fi_design_id"):
            continue
        for ax in all_axes:
            totals[f"{ax}_truncated"] += len(cuts.get(ax) or [])
    return totals


def summarize_hidden_io(itcs: List[Dict[str, Any]]) -> Dict[str, int]:
    """흐름 통계(`sits._FLOW_COV_KEYS`)로 나가는 스칼라 — 품질 리포트 `integration_flow_coverage` · 공시 `sits_hidden_inputs`."""
    recs = [t.get(RECORD_KEY) for t in itcs or [] if isinstance(t.get(RECORD_KEY), dict)]
    return {
        "hidden_io_tcs": sum(1 for r in recs if any(r.get(k) for k in ("inputs_shown", "inputs_over_cap",
                                                                        "expected_shown", "expected_over_cap"))),
        "hidden_inputs_shown": sum(len(r.get("inputs_shown") or []) for r in recs),
        "hidden_expected_shown": sum(len(r.get("expected_shown") or []) for r in recs),
        "hidden_inputs_over_cap": sum(len(r.get("inputs_over_cap") or []) for r in recs),
        "hidden_expected_over_cap": sum(len(r.get("expected_over_cap") or []) for r in recs),
        "hidden_input_rows_not_in_document": sum(int(r.get("rows_input_not_in_document") or 0) for r in recs),
        "hidden_input_cells_downgraded": sum(int(r.get("downgraded_cells") or 0) for r in recs),
    }


def hidden_io_by_tc(itcs: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[str]]]:
    """품질 리포트용 TC 별 이름 — 열로 보인 이름 · 상한에 막힌 이름이 있는 TC 만."""
    out: Dict[str, Dict[str, List[str]]] = {}
    for t in itcs or []:
        r = t.get(RECORD_KEY)
        if not isinstance(r, dict):
            continue
        got = {k: list(r.get(k) or []) for k in ("inputs_shown", "inputs_over_cap", "expected_shown",
                                                  "expected_over_cap") if r.get(k)}
        if got:
            out[str(t.get("tc_id") or "")] = got
    return out


# ── S2: 계획(순수 함수) ─────────────────────────────────────────────────────────────────────────────────────────────

#: 막힌 칸의 사유 → 등급. 순위의 첫 키다(앞일수록 먼저).
#:   observed_initial — 쓰지 않은 출력의 최종값(=초기값)을 관측하려면 그 값이 필요하다(`unwritten_output_initial_not_in_inputs:K`)
#:   value_read       — 실행 모델이 값을 읽다 막혔다(`initial_value_not_in_inputs:K` · `parameter_not_in_inputs:P`)
#:   decision         — 모르는 값으로 분기가 갈렸다(`path_dependent:branch_on_unknown:…:K`)
TIERS: Tuple[str, ...] = ("observed_initial", "value_read", "decision")
_TIER_RANK = {t: i for i, t in enumerate(TIERS)}
_KIND_TIER = {"unwritten_output_initial_not_in_inputs": "observed_initial",
              "initial_value_not_in_inputs": "value_read", "parameter_not_in_inputs": "value_read"}
# 이름을 넓게 잡는다 — 2 차원 첨자 · 배열 뒤 멤버도 잡아 **사유와 함께** 거른다(`_SOURCE_READ_RE` 는 그런 이름을 조용히 놓친다)
_BROAD_RE = re.compile(r"(?<![\w])(unwritten_output_initial_not_in_inputs|initial_value_not_in_inputs|parameter_not_in_inputs)"
                       r":([A-Za-z_][\w.\[\]]*)")
_DECISION_MARK = "branch_on_unknown:"
_STUB_RE = re.compile(r"\(\)\s")   # `F() return` · `F() p[0]` — 시퀀스 stub 입력(값을 주면 그 callee 를 stub 한다)


def _blocking_names(reason: str) -> List[Tuple[str, str]]:
    """사유 하나 → [(등급, 이름)]. 분기 사유(`…branch_on_unknown:…`) 안의 이름은 `decision`."""
    r = str(reason or "")
    pos = r.find(_DECISION_MARK)
    out: List[Tuple[str, str]] = []
    for m in _BROAD_RE.finditer(r):
        tier = "decision" if 0 <= pos < m.start() else _KIND_TIER[m.group(1)]
        out.append((tier, m.group(2)))
    return out


def needed_inputs(itc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """막힌 칸의 사유에서 **값이 없어 막힌 이름** → ``{"tier", "cells", "rows", "first"}``.

    ``cells`` = 그 이름이 막은 칸 수, ``rows`` = 행 위치(0 부터, 오름차순), ``first`` = (행, 기대 열 위치) 중 가장 앞(열에 없는 기대값은
    열 수 뒤로 친다). 한 이름이 여러 등급으로 나오면 가장 앞 등급. 확정 칸 · 이름 없는 사유는 보지 않는다. 결과는 순서와 무관하다
    (같은 증거를 어떤 순서로 줘도 같다).
    """
    cols = {n: i for i, n in enumerate(itc.get("expected_vars") or [])}
    out: Dict[str, Dict[str, Any]] = {}
    for r, sc in enumerate(itc.get("sub_cases") or []):
        for var, ev in ((sc or {}).get("expected_evidence") or {}).items():
            if not isinstance(ev, dict) or ev.get("status") == "derived":
                continue
            where = (r, cols.get(var, len(cols)))
            for tier, name in _blocking_names(str(ev.get("reason") or "")):
                rec = out.get(name)
                if rec is None:
                    out[name] = {"tier": tier, "cells": 1, "rows": [r], "first": where}
                    continue
                rec["cells"] += 1
                if _TIER_RANK[tier] < _TIER_RANK[rec["tier"]]:
                    rec["tier"] = tier
                if r not in rec["rows"]:
                    rec["rows"] = sorted(rec["rows"] + [r])
                rec["first"] = min(rec["first"], where)
    return out


def _shape_ok(name: str) -> bool:
    """`generators.suts._SOURCE_READ_RE` 가 받는 이름 모양(1 차원 첨자 · 배열 앞 멤버만) — 시험 입력 한 칸으로 줄 수 있는 모양."""
    from generators.c_source_oracle import INITIAL_VALUE_PREFIX
    from generators.suts import _SOURCE_READ_RE
    return bool(_SOURCE_READ_RE.fullmatch(INITIAL_VALUE_PREFIX + str(name)))


def _storage_prefixes(name: str) -> List[str]:
    """`REG.Bits.F` → [`REG`, `REG.Bits`], `a[3]` → [`a`] — 그 이름을 담는 저장소 경로들."""
    out: List[str] = []
    for m in re.finditer(r"[.\[]", name):
        out.append(name[:m.start()])
    return out


def _structural_reason(name: str, rec: Dict[str, Any], columns: set) -> str:
    if _STUB_RE.search(name):
        return "stub_input"
    if not _shape_ok(name):
        return "subscript_shape"
    if name in columns:
        return "already_a_column"
    if any(p in columns for p in _storage_prefixes(name)):
        return "storage_root_already_set"
    if int(rec.get("cells") or 0) <= 0:
        return "blocks_no_cell"
    return ""


def _domain_reason(rd: Any) -> str:
    """`sits.ResolvedDomain` → 거르는 사유(``""`` = 값을 정할 수 있다)."""
    if rd.type_reason in ("struct_object", "pointer_object"):
        return rd.type_reason
    if rd.domain is None:
        return "unknown_type:" + (rd.type_reason or rd.documented_reason or "unresolved")
    if _axis(rd.domain) is None:
        return "float_not_ranged"
    return ""


def exclude_needed(needed: Dict[str, Dict[str, Any]], itc: Dict[str, Any],
                   resolve: Optional[Callable[..., List[Any]]] = None,
                   raws: Optional[Dict[str, str]] = None) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """(열로 올릴 수 있는 이름, {거른 이름: 사유}).

    사유(앞부터 먼저 걸린 것): ``stub_input``(`F() return` — 값을 주면 그 callee 가 stub 이 된다) · ``subscript_shape``(2 차원 첨자 ·
    배열 뒤 멤버) · ``already_a_column`` · ``storage_root_already_set``(그 이름을 담는 저장소 — 레지스터 통째 등 — 가 이미 열) ·
    ``blocks_no_cell`` · ``resolve`` 를 주면 도메인: ``struct_object`` · ``pointer_object`` · ``unknown_type:<사유>`` ·
    ``float_not_ranged``. ``resolve`` 는 `sits._input_domain_resolver` 의 반환(체인 함수는 ``itc["chain_functions"]``).
    """
    columns = set(itc.get("input_vars") or [])
    kept: Dict[str, Dict[str, Any]] = {}
    excluded: Dict[str, str] = {}
    for name in sorted(needed):
        why = _structural_reason(name, needed[name], columns)
        if why:
            excluded[name] = why
        else:
            kept[name] = needed[name]
    if resolve is not None and kept:
        names = sorted(kept)
        got = resolve(names, [(raws or {}).get(n, "") for n in names], list(itc.get("chain_functions") or []))
        for name, rd in zip(names, got, strict=True):
            why = _domain_reason(rd)
            if why:
                excluded[name] = why
                kept.pop(name)
    return kept, excluded


def _rank_key(name: str, rec: Dict[str, Any]) -> Tuple[Any, ...]:
    m = re.match(r"[A-Za-z_]\w*", name)
    root = m.group(0) if m else name
    sub = re.search(r"\[(\d+)\]", name)
    first = tuple(rec.get("first") or (0, 0))
    return (_TIER_RANK.get(str(rec.get("tier")), len(TIERS)), -int(rec.get("cells") or 0), first[0], first[1],
            root, int(sub.group(1)) if sub else -1, name)


def rank_needed(needed: Dict[str, Dict[str, Any]]) -> List[str]:
    """순위 — 등급 → 막은 칸 많은 순 → 처음 나온 자리(행, 기대 열) → (뿌리 이름, 숫자 첨자, 이름). 전순서라 입력 순서와 무관하다."""
    return sorted(needed, key=lambda n: _rank_key(n, needed[n]))


def _axis(dom: Dict[str, Any]) -> Any:
    """도메인 → `boundary_rows` 의 축(정수 범위 ``(lo, hi)`` 또는 값 목록). 실수는 None."""
    kind = dom.get("kind")
    if kind == "enum":
        return list(dom["values"])
    if kind == "documented":
        vals = list(dom.get("values") or [])
        return vals if vals else (int(dom["vlo"]), int(dom["vhi"]))
    if kind == "range":
        return (int(dom["lo"]), int(dom["hi"]))
    from generators.sits import _domain_representable
    rep = _domain_representable(dom)
    return None if rep is None else (int(rep[0]), int(rep[1]))


def _contains(axis: Any, v: Any) -> bool:
    if isinstance(axis, list):
        return v in axis
    return isinstance(v, int) and not isinstance(v, bool) and axis[0] <= v <= axis[1]


def select_values(ranked: Sequence[str], resolve: Callable[..., List[Any]], functions: Sequence[str] = (),
                  raws: Optional[Dict[str, str]] = None) -> Tuple[Dict[str, int], Dict[str, str]]:
    """순위대로 값을 **한 번** 정한다 — ({이름: 값}, {못 정한 이름: 사유}).

    도메인은 ``resolve``(`sits._input_domain_resolver` — 선언 타입 ∩ 체인 함수 ``functions`` 의 SwUDS 범위), 출발값은 그 도메인의
    EC4 가운데 값(`sits._typed_boundary_values(dom)[0][3]`), 그다음 `boundary_rows.blank_fill` 을 순위 순서로 — 넓은 범위면 순위
    위치만큼 옮겨 두 입력이 같은 값이 되지 않게(R19 규칙), 값 목록이면 목록 안 값. 값 목록이 `blank_fill` 상한보다 커 축에서 빠지면
    가운데 값(목록 안 값) 그대로. 역할 값(경계 · 강건성)은 쓰지 않는다 — R19 교훈(정상 행 값이 미정의 동작을 열어 칸을 잃었다).
    """
    from generators.boundary_rows import blank_fill
    from generators.sits import _typed_boundary_values
    names = list(ranked)
    excluded: Dict[str, str] = {}
    if not names:
        return {}, excluded
    got = resolve(names, [(raws or {}).get(n, "") for n in names], list(functions))
    domains: Dict[str, Any] = {}
    defaults: Dict[str, int] = {}
    for name, rd in zip(names, got, strict=True):
        why = _domain_reason(rd)
        if why:
            excluded[name] = why
            continue
        axis = _axis(rd.domain)
        mid = _typed_boundary_values(rd.domain)[0][3]
        if not _contains(axis, mid):
            excluded[name] = "no_value_in_domain"
            continue
        domains[name] = axis      # 순위 순서로 넣는다 — `blank_fill` 의 위치 이동이 이 순서를 따른다
        defaults[name] = mid
    fill = blank_fill(domains, defaults)
    values: Dict[str, int] = {}
    for name in names:
        if name in fill:
            values[name] = fill[name]
        elif name in defaults:
            values[name] = defaults[name]
    return values, excluded


__all__ = ["DERIVATION_FIELDS", "INPUT_NOT_IN_DOCUMENT", "RECORD_KEY", "ROW_MARK", "TIERS",
           "downgrade_hidden_input_rows", "exclude_needed", "hidden_io_by_tc", "needed_inputs", "rank_needed",
           "reconcile_candidate_cuts", "render_hidden_inputs", "select_values", "summarize_hidden_io"]
