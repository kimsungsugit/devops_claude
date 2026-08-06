"""SCM 레지스트리에 등록된 연결 문서가 **실제로 있는지** 점검한다.

## 왜 필요한가

`config/scm_registry.json` 의 문서 경로는 문서가 개정되며 파일명이 바뀌면 조용히
낡는다. 화면의 '입력 문서 현황' 은 경로 문자열이 비어있지 않은 것만 보고 `등록됨`
을 달았기 때문에, 파일이 사라져도 배지는 그대로인데 추적성 매트릭스만 실패했다 —
사용자에게는 *"문서가 있는데 없다고 나온다"* 로 보인다.

실측(2026-08-06): `kjpds02` 항목은 등록된 문서 11개 중 **8개가 실물 없음**이었고,
SRS 는 `_v2.03_….docx` 로 등록됐는데 폴더엔 `_v3.01_…_R.docx` 하나뿐이었다.

## 사용법

    backend/.venv/Scripts/python.exe scripts/check_linked_docs.py
    backend/.venv/Scripts/python.exe scripts/check_linked_docs.py --entry kjpds02
    backend/.venv/Scripts/python.exe scripts/check_linked_docs.py --entry kjpds02 --srs-gate

`--srs-gate` 는 `/api/jenkins/uds/requirements-preview` 의 요구문서 읽기 관문을
순서대로 밟아 **어느 단계에서 탈락하는지** 보여준다(접근검사 → 존재 → 형식 →
read → 본문추출 → 요구 인식).

## ⚠ 인터프리터

반드시 **`backend/.venv`** 로 실행할 것. 맨 `python` 은 mingw 를 잡아 bcrypt 등이
없어 import 단계에서 죽는다(CLAUDE.md '인터프리터 규칙').

## ⚠ prefix 병합

cloudium resolver 는 deny-by-default 다. `allowed_prefixes` 병합은 backend
lifespan 에서만 일어나므로, 독립 스크립트는 아래 `_bootstrap_resolver()` 처럼
**SCM 경로 + extra prefixes 를 직접 병합**해야 한다. 빼먹으면 전부 '접근 거부'로
나와 진단이 정반대가 된다.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# 한글 경로/사유가 콘솔 인코딩에 걸려 깨지지 않게.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REGISTRY = REPO / "config" / "scm_registry.json"


def _bootstrap_resolver():
    """backend lifespan(main.py) 과 동일한 prefix 병합을 재현한다."""
    notes: list[str] = []
    try:
        from backend.routers.scm import merge_all_scm_paths_to_cloudium
        notes.append(f"SCM prefix 병합: {merge_all_scm_paths_to_cloudium()}")
    except Exception as exc:  # noqa: BLE001 — 부트스트랩 실패는 진단을 무의미하게 만든다. 보고한다
        notes.append(f"⚠ SCM prefix 병합 실패: {type(exc).__name__}: {exc}")
    try:
        from backend.routers.health import _apply_extra_prefixes_to_resolver
        from backend.services.cloudium_extra_prefixes import load_extra_prefixes
        extra = load_extra_prefixes()
        if extra:
            _apply_extra_prefixes_to_resolver(extra)
        notes.append(f"extra prefixes: {len(extra or [])}건")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"⚠ extra prefixes 병합 실패: {type(exc).__name__}: {exc}")

    from backend.services.file_resolver import CloudiumFileResolver, get_resolver
    resolver = get_resolver()
    notes.append(f"file mode: {resolver.mode}")
    if isinstance(resolver, CloudiumFileResolver):
        notes.append(f"allowed_prefixes: {len(resolver.allowed_prefixes)}개")
    return resolver, notes


def _probe(resolver, path: str) -> tuple[str, str]:
    """(상태, 사유). 상태는 'OK' | 'MISSING' | 'UNKNOWN'.

    ⚠ 확인 실패를 MISSING 으로 접지 않는다 — '없다'와 '못 봤다'는 다른 말이고,
    접으면 IPC 한 번 실패에 멀쩡한 문서가 '없음'으로 보고된다.
    """
    try:
        return ("OK", "") if resolver.exists(path) else ("MISSING", "")
    except PermissionError as exc:
        return "UNKNOWN", f"접근 거부 — {str(exc)[:140]}"
    except Exception as exc:  # noqa: BLE001 — resolver/IPC 계열이 광범위
        return "UNKNOWN", f"확인 실패 ({type(exc).__name__}: {str(exc)[:120]})"


def audit(resolver, entries) -> int:
    """등록 문서 존재 여부 감사. 반환값 = 문제(MISSING+UNKNOWN) 총건수."""
    problems = 0
    for entry in entries:
        linked = entry.get("linked_docs") or {}
        rows: list[tuple[str, str, str, str]] = []
        for key, value in linked.items():
            for path in (value if isinstance(value, list) else ([value] if value else [])):
                if not str(path or "").strip():
                    continue
                state, reason = _probe(resolver, str(path))
                rows.append((key, str(path), state, reason))
        bad = [r for r in rows if r[2] != "OK"]
        problems += len(bad)
        print(f"\n[{entry.get('id')}] {entry.get('name')} — 등록 {len(rows)}개 / 문제 {len(bad)}건")
        for key, path, state, reason in rows:
            if state == "OK":
                continue
            mark = "✗ 없음  " if state == "MISSING" else "? 모름  "
            print(f"   {mark}{key:9s} …{path[-72:]}")
            if reason:
                print(f"              → {reason}")
        if not bad:
            print("   ✓ 전부 확인됨")
    return problems


def srs_gate(entry) -> None:
    """requirements-preview 의 요구문서 관문을 순서대로 밟는다.

    resolver 를 인자로 받지 않는다 — `read_requirement_doc_via_resolver` 가 내부에서
    `get_resolver()` 를 부르므로, 여기서 따로 넘기면 **두 개의 resolver 를 쓰는 것처럼
    보여** 부트스트랩을 빼먹어도 통과하는 착시가 생긴다(시뮬↔라이브 정합).
    """
    from backend.helpers.common import _is_allowed_req_doc
    from backend.services.resolver_helpers import read_requirement_doc_via_resolver

    srs = (entry.get("linked_docs") or {}).get("srs") or ""
    print(f"\n=== SRS 관문 [{entry.get('id')}] ===\n  {srs or '(미등록)'}")
    if not srs:
        print("  → 경로 미지정 — 설정 탭 또는 SCM 연결 문서에서 등록해야 한다")
        return

    text, reason = read_requirement_doc_via_resolver(srs, allow=_is_allowed_req_doc)
    if reason:
        print(f"  ✗ 탈락 — {reason}")
        return
    print(f"  ✓ 본문 {len(text):,}자")

    from report_gen.requirements import generate_uds_requirements_preview
    items = (generate_uds_requirements_preview([text]) or {}).get("items") or []
    print(f"  ✓ 요구사항 {len(items)}건 인식")
    if not items:
        print("  ⚠ 문서는 읽혔는데 요구 ID 0건 — 경로가 아니라 **양식** 문제다")
    for item in items[:3]:
        print(f"      예: {str(item)[:110]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="SCM 등록 문서 실물 점검")
    ap.add_argument("--entry", default="", help="특정 SCM id 만 (미지정 시 전체)")
    ap.add_argument("--srs-gate", action="store_true",
                    help="SRS 읽기 관문을 단계별로 밟아 탈락 지점 표시")
    args = ap.parse_args()

    if not REGISTRY.exists():
        print(f"레지스트리가 없다: {REGISTRY}")
        return 2
    store = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entries = store.get("registries") or []
    if args.entry:
        entries = [e for e in entries if e.get("id") == args.entry]
        if not entries:
            print(f"그런 SCM id 가 없다: {args.entry}")
            return 2

    resolver, notes = _bootstrap_resolver()
    for note in notes:
        print(note)

    problems = audit(resolver, entries)
    if args.srs_gate:
        for entry in entries:
            srs_gate(entry)

    print(f"\n=== 문제 총 {problems}건 ===")
    # 문제가 있으면 비-0 — CI/스크립트에서 게이트로 쓸 수 있게.
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
