#!/usr/bin/env python
"""RAG KB 벡터 재인덱싱 CLI.

## 왜 필요한가

임베딩 백엔드(Gemini 키 등)를 새로 붙여도 **기존 KB 벡터는 그대로**다. 예전 벡터가
64차원 무작위 폴백이면 새 질의(768차원)와 차원이 달라 `semantic_search` 가 전량 제외한다 —
즉 백엔드를 붙여도 시맨틱 축이 복구되지 않고, 그 사실은 카운터에만 남는다. 이 저장소의
실 KB 102건이 정확히 그 상태였고 되살릴 경로가 **없었다**.

## 사용

    .venv/Scripts/python.exe scripts/reindex_kb.py <kb_store_dir> [--dry-run] [--force] [--limit N]

`<kb_store_dir>` 은 `kb_store` 디렉터리 또는 그 부모(reports 세션 디렉터리)를 준다.

- `--dry-run`: 계산·쓰기 없이 대상 건수만 센다. **먼저 이걸로 확인할 것.**
- `--force`: 이미 현재 model+dim 인 엔트리도 다시 계산 + 백엔드가 열화 상태여도 진행.
  기본은 열화 시 **거부**한다(무작위 벡터로 덮어쓰는 무의미한 쓰기 방지).
- `--limit N`: 처리 상한(대용량 KB 를 나눠 돌릴 때).

⚠ 엔트리 파일과 sqlite/pgvector 를 모두 갱신한다. 되돌릴 수 없으니 `--dry-run` 먼저.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description="RAG KB 벡터 재인덱싱")
    ap.add_argument("kb_dir", help="kb_store 디렉터리 또는 그 부모")
    ap.add_argument("--dry-run", action="store_true", help="계산·쓰기 없이 대상만 센다")
    ap.add_argument("--force", action="store_true",
                    help="최신 벡터도 재계산 + 백엔드 열화 상태에서도 진행")
    ap.add_argument("--limit", type=int, default=None, help="처리 상한")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    base = Path(args.kb_dir).expanduser().resolve()
    if not base.exists():
        print(f"ERROR: 경로가 없다: {base}", file=sys.stderr)
        return 2
    # kb_store 를 직접 줬는지, 부모를 줬는지 자동 판별
    if base.name != "kb_store" and (base / "kb_store").is_dir():
        base = base / "kb_store"

    from workflow.rag import KnowledgeBase

    kb = KnowledgeBase(base)
    print(f"KB: {base}  엔트리 {len(kb.data)}건  storage={kb.storage}")

    stats = kb.reindex_embeddings(force=args.force, dry_run=args.dry_run, limit=args.limit)
    print(json.dumps(stats, ensure_ascii=False, indent=2))

    if stats.get("aborted_reason"):
        print("\n중단됨 — 위 사유를 해결하거나 --force 를 쓸 것.", file=sys.stderr)
        return 1
    if stats.get("failed"):
        print(f"\n⚠ {stats['failed']}건 실패 — 로그를 확인할 것.", file=sys.stderr)
        return 1
    if stats.get("text_field_guessed"):
        print(f"\n⚠ {stats['text_field_guessed']}건은 임베딩 원본 필드 기록이 없어 "
              "휴리스틱(context→error_clean→fix)으로 골랐다. 신규 엔트리는 "
              "metadata.embed.text_field 에 기록되므로 다음부터는 정확하다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
