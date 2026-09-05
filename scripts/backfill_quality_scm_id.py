"""품질 이력의 과거 행에 `scm_id`(프로젝트 축)를 채운다 — 기본은 dry-run.

## 왜 필요한가

`GenerationRun.scm_id` 는 신규 기록부터 채워지지만, 이미 쌓인 행(2026-08-07 실측
964건)은 NULL 이라 "이 프로젝트의 품질 이력" 화면에서 통째로 빠진다. 이 스크립트가
`project_root` 의 어휘를 registry entry id 로 되짚어 1회 채운다.

## 판정은 여기서 하지 않는다

매핑은 `backend.services.scm_registry.resolve_scm_id()` **한 함수**가 전부 결정한다.
런타임 기록(`workflow/quality/recorder.py`)이 쓰는 바로 그 함수다. 백필용 규칙을
따로 쓰면 같은 입력이 두 값으로 갈리고, 그건 이 저장소가 이미 네 번 겪은 실패다
(`_is_hsis_data_row` · `_ratchet_core` · `_artifact_check` · 게이트 사이드카 파서).

그 함수는 **정확일치만** 인정한다 — 부분일치·최장접두·"후보가 하나뿐이니 그거겠지"
폴백을 하지 않는다. 근거가 없는 행은 NULL 로 남고, 아래 표에 `(미상)` 으로 보고된다.
잘못 귀속된 행은 조용히 틀린 화면을 만들지만, NULL 은 화면에서 눈에 띈다.

## 사용

    .venv/Scripts/python.exe scripts/backfill_quality_scm_id.py              # dry-run
    .venv/Scripts/python.exe scripts/backfill_quality_scm_id.py --apply      # 실제 반영
    .venv/Scripts/python.exe scripts/backfill_quality_scm_id.py --db path/to/q.sqlite
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Dict, List, Optional, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_NULL_LABEL = "(NULL)"
_UNKNOWN_LABEL = "(미상)"


def _plan(session, resolve) -> Tuple[List[Tuple[str, int, Optional[str]]], int, int]:
    """(project_root, 건수, 해결된 scm_id) 목록과 mapped/unmapped 행 수를 낸다.

    project_root 고유값별로 **한 번만** 해결한다 — registry 는 파일 I/O 라
    행마다 부르면 964회 읽는다.
    """
    from workflow.quality.models import GenerationRun

    rows = (
        session.query(GenerationRun.project_root)
        .filter(GenerationRun.scm_id.is_(None))
        .all()
    )
    counts: Dict[str, int] = {}
    for (root,) in rows:
        counts[str(root) if root else ""] = counts.get(str(root) if root else "", 0) + 1

    cache: Dict[str, Optional[str]] = {}
    plan: List[Tuple[str, int, Optional[str]]] = []
    mapped = unmapped = 0
    for root, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if root not in cache:
            cache[root] = resolve(root) if root else None
        hit = cache[root]
        plan.append((root, n, hit))
        if hit:
            mapped += n
        else:
            unmapped += n
    return plan, mapped, unmapped


def _print_table(plan) -> None:
    if not plan:
        print("  (scm_id 가 NULL 인 행이 없다 — 백필할 것이 없음)")
        return
    width = max(len(r or _NULL_LABEL) for r, _, _ in plan)
    width = max(min(width, 60), len("project_root"))
    print(f"  {'project_root'.ljust(width)}  {'건수':>6}  → scm_id")
    print(f"  {'-' * width}  {'-' * 6}  {'-' * 12}")
    for root, n, hit in plan:
        label = (root or _NULL_LABEL)
        if len(label) > width:
            label = "…" + label[-(width - 1):]
        print(f"  {label.ljust(width)}  {n:>6}  → {hit or _UNKNOWN_LABEL}")


def main(argv=None) -> int:
    # `-O` 로 돌면 __doc__ 이 None 이라 리터럴로 둔다.
    ap = argparse.ArgumentParser(description="품질 이력 과거 행에 scm_id 를 채운다")
    ap.add_argument("--apply", action="store_true", help="실제로 UPDATE (기본은 dry-run)")
    ap.add_argument("--db", default="", help="Quality DB 경로 (생략 시 기본 경로)")
    args = ap.parse_args(argv)

    from backend.services.scm_registry import list_registry_entries, resolve_scm_id
    from workflow.quality.db import get_session, init_db
    from workflow.quality.models import GenerationRun

    db_path = pathlib.Path(args.db) if args.db else None

    entries = list_registry_entries()
    print(f"registry 항목 {len(entries)}개: " + (", ".join(str(e.id) for e in entries) or "(없음)"))
    if not entries:
        print("⚠ registry 가 비어 있다 — 매핑할 근거가 없으므로 전부 미상으로 남는다.")

    # 컬럼이 없는 구 스키마면 여기서 추가된다(조회가 죽지 않도록).
    init_db(db_path)

    with get_session(db_path) as session:
        plan, mapped, unmapped = _plan(session, resolve_scm_id)

        print()
        _print_table(plan)
        print()
        print(f"매핑 가능 {mapped}행 / 미상 {unmapped}행")

        if not args.apply:
            print("\n(dry-run — 아무것도 바꾸지 않았다. 반영하려면 --apply)")
            return 0

        if mapped == 0:
            print("\n반영할 행이 없다.")
            return 0

        updated = 0
        for root, _n, hit in plan:
            if not hit:
                continue
            q = session.query(GenerationRun).filter(GenerationRun.scm_id.is_(None))
            q = q.filter(GenerationRun.project_root == root) if root else q.filter(
                GenerationRun.project_root.is_(None)
            )
            updated += q.update({GenerationRun.scm_id: hit}, synchronize_session=False)

        print(f"\n{updated}행 갱신 완료 (미상 {unmapped}행은 NULL 유지)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
