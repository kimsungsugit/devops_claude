# generators/_artifact_check.py
"""생성 수 ↔ 파일에 기록된 수 대조 — 세 생성기(STS/SUTS/SITS) 공용 단일 출처.

## 왜 필요한가

세 생성기 모두 파이프라인이 이런 모양이다:

    out = generate_*_xlsm(...)      # N건을 파일에 쓴다
    validation = validate_*_xlsm(out)   # 파일에서 K건을 되읽는다
    return {"test_case_count": N, "validation": validation}   # ← N 과 K 를 **대조하지 않는다**

`validate_*` 는 `K == 0` 만 본다. 그래서 라이터가 절반을 흘려도 `valid: True` 가 나오고,
호출자에게 돌아가는 `test_case_count` 는 파일이 아니라 **생성기가 세어준 N** 이다.
"검증했다"는 산출물이 실제로는 파일 내용을 검증하지 않는다.

2026-07-29 실측에서는 라이터 자체는 정직했다(SITS 1288/1288 sub-case, SUTS 900/900 TC ·
7269/7269 sequence 전부 기록됨). 즉 이 대조는 **지금 깨진 것을 잡는 게 아니라, 앞으로
라이터가 조용히 흘리기 시작하면 그때 걸리게 하는 것**이다. 같은 라운드에서 SITS 검증기가
sub-case 를 34.8% 과소 계수하고 있었던 것처럼(라이터 포맷 변경을 리더 휴리스틱이 못 따라감),
이 계층은 실제로 어긋난다.

## 판정 로직을 여기 한 곳에만 두는 이유

이 저장소는 같은 판정을 여러 파일에 복제했다가 한쪽만 고쳐져 다른 쪽이 잠복한 전례가
여러 번 있다(`_is_hsis_data_row` 단일화, ruff/eslint ratchet `_ratchet_core` 단일화).
대조 규칙은 세 생성기가 **글자 그대로 같은 함수**를 쓴다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

__all__ = ["compare_generated_vs_written", "apply_write_back_check"]


def compare_generated_vs_written(
    expected: Mapping[str, int],
    stats: Mapping[str, Any],
) -> List[str]:
    """생성 수(`expected`)와 되읽은 수(`stats`)를 대조해 불일치를 사람이 읽는 문장으로.

    Args:
        expected: {통계키: 생성기가 실제로 만든 개수}
        stats: `validate_*_xlsm(...)["stats"]` — 파일에서 되읽은 개수

    Returns:
        불일치 설명 목록. 일치하면 빈 리스트.

    ⚠ `stats` 에 키가 **없으면 통과가 아니라 "대조 불가"** 로 남긴다. 미측정을 통과로
    바꾸는 것이 이 저장소가 반복해 고쳐 온 fail-open 이다(검증 크래시를 valid:True 로
    쓰던 STS B7 건과 같은 부류).
    """
    issues: List[str] = []
    for key in sorted(expected):
        want = expected[key]
        if key not in stats or stats[key] is None:
            issues.append(
                f"{key}: 생성 {want}건인데 파일에서 되읽지 못했다 — 대조 불가(미검증)"
            )
            continue
        try:
            got = int(stats[key])
            want_i = int(want)
        except (TypeError, ValueError):
            issues.append(f"{key}: 수치가 아니어서 대조 불가(생성={want!r}, 파일={stats[key]!r})")
            continue
        if got != want_i:
            issues.append(
                f"{key}: 생성 {want_i}건 → 파일 {got}건 ({got - want_i:+d}) — "
                f"기록 과정에서 어긋났다"
            )
    return issues


def apply_write_back_check(
    validation: Dict[str, Any],
    expected: Mapping[str, int],
) -> Dict[str, Any]:
    """`validation` 결과에 생성↔기록 대조를 합쳐서 돌려준다(제자리 갱신).

    불일치가 있으면 `issues` 에 추가하고 `valid` 를 False 로 내린다. 대조 결과 자체는
    `stats["write_back_check"]` 에 남겨, 소비처가 "대조를 했고 통과했다"와 "대조를 아예
    안 했다"를 구분할 수 있게 한다(둘 다 issues 가 비어 있어 구분이 안 되면 무의미하다).
    """
    if not isinstance(validation, dict):
        validation = {"valid": False, "issues": ["validation 결과가 dict 가 아니다"], "stats": {}}

    stats = validation.get("stats")
    if not isinstance(stats, dict):
        stats = {}
        validation["stats"] = stats

    mismatches = compare_generated_vs_written(expected, stats)
    stats["write_back_check"] = {
        "expected": dict(expected),
        "mismatches": mismatches,
        "passed": not mismatches,
    }

    if mismatches:
        existing = validation.get("issues")
        validation["issues"] = list(existing) if isinstance(existing, list) else []
        validation["issues"].extend(mismatches)
        validation["valid"] = False

    return validation
