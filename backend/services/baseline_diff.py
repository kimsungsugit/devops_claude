"""베이스라인→최신 소스 스냅샷 직접 비교 — change-log(영향분석 이력) 완전 비의존.

요약탭 "베이스라인 기준 변화": 사용자가 영향분석을 실행했는지와 무관하게, 캐시된 두 빌드의
source/ 스냅샷을 직접 비교해 파일/함수 변화를 낸다(Jenkins/SVN 불필요).

방법(method 필드로 응답에 명시):
- 파일 add/deleted/modified: 상대경로 조인 + 내용 sha1 비교(.c/.h 한정).
- 함수 분류: **파서 권위** — 두 스냅샷을 parse_c_project로 파싱해 (파일, 함수명) 조인:
  한쪽에만 존재→NEW/DELETE, signature 다름→SIGNATURE(before/after 원문 동반),
  signature 같고 body 다름→BODY. ⚠ diff 텍스트 분류기(delta_update)는 svn `-x -p`의
  함수 컨텍스트를 요구하는데 difflib은 이를 생성하지 못해(BODY 귀속 불가 — 모듈 주석
  경고) 재사용하지 않는다. 파일 이동은 DELETE+NEW로 나타난다(한계 명시).
- ASIL: 함수 주석 @asil(comment_asil) 조인 — asil_touched로 강조(ISO: 안전 함수 변경 가시화).

정직성: 스냅샷 부재/단일 빌드는 reason으로 정직 실패. 비교 불가를 '변화 0'으로 위장하지 않는다.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BASELINE_DIFF_ALGO_VERSION = 1
_SRC_EXTS = {".c", ".h"}
_EXCLUDE_DIRS = {".svn", ".git"}
_WS = re.compile(r"\s+")


def _norm_code(s: str) -> str:
    """공백 정규화 비교 — 개행/들여쓰기 리포맷을 변경으로 오인하지 않게."""
    return _WS.sub(" ", str(s or "")).strip()


def _iter_src_files(source: Path) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    try:
        for p in source.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in _SRC_EXTS:
                continue
            if any(seg in _EXCLUDE_DIRS for seg in p.parts):
                continue
            rel = str(p.relative_to(source)).replace("\\", "/")
            out[rel] = p
    except OSError:
        pass
    return out


def _sha1(path: Path) -> Optional[str]:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def snapshot_fingerprint(source: Path) -> Optional[Dict[str, Any]]:
    """스냅샷 지문(stat 스캔 — 내용 해시 아님, 완결 스냅샷 불변 전제). 부재는 None."""
    if not (source / ".source_complete").exists():
        return None
    files = 0
    total = 0
    try:
        for p in source.rglob("*"):
            if p.is_file():
                files += 1
                total += p.stat().st_size
    except OSError:
        return None
    return {"file_count": files, "total_bytes": total, "algo_version": BASELINE_DIFF_ALGO_VERSION}


def _parse_functions(source: Path, *, max_files: int = 1200) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """(상대파일, 함수명) → {signature, body_norm, asil}. 파싱 실패는 예외 전파(호출측 reason화)."""
    from workflow.code_parser.c_parser import parse_c_project

    parsed = parse_c_project(str(source), max_files=max_files, preprocess=False)
    prefix = str(source.resolve()).replace("\\", "/").rstrip("/") + "/"
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for f in parsed.get("functions") or []:
        name = str(f.get("name") or "")
        if not name:
            continue
        raw_file = str(f.get("file") or "").replace("\\", "/")
        rel = raw_file[len(prefix):] if raw_file.lower().startswith(prefix.lower()) else raw_file
        out[(rel, name)] = {
            "signature": str(f.get("signature") or "").strip(),
            "sig_norm": _norm_code(f.get("signature")),
            "body_norm": _norm_code(f.get("body")),
            "asil": (str(f.get("comment_asil") or "").strip() or None),
        }
    return out


def compute_baseline_diff(*, baseline_source: Path, target_source: Path) -> Dict[str, Any]:
    """두 스냅샷 비교(순수 계산 — 캐시는 라우터). 파일 3분류 + 함수 파서 권위 분류."""
    t0 = time.time()
    base_files = _iter_src_files(baseline_source)
    tgt_files = _iter_src_files(target_source)
    added = sorted(set(tgt_files) - set(base_files))
    deleted = sorted(set(base_files) - set(tgt_files))
    modified: List[Dict[str, Any]] = []
    unchanged = 0
    for rel in sorted(set(base_files) & set(tgt_files)):
        h1, h2 = _sha1(base_files[rel]), _sha1(tgt_files[rel])
        if h1 is None or h2 is None:
            continue
        if h1 == h2:
            unchanged += 1
            continue
        try:
            a = base_files[rel].read_text(encoding="utf-8", errors="ignore").splitlines()
            b = tgt_files[rel].read_text(encoding="utf-8", errors="ignore").splitlines()
            import difflib

            la = sum(1 for line in difflib.ndiff(a, b) if line.startswith("+ "))
            lr = sum(1 for line in difflib.ndiff(a, b) if line.startswith("- "))
        except Exception:  # silent-ok: 라인 수는 표시 부가정보 — 실패는 null로 정직 표기(변경 사실은 sha1이 이미 확정)
            la = lr = None
        modified.append({"path": rel, "lines_added": la, "lines_removed": lr})

    base_fns = _parse_functions(baseline_source)
    tgt_fns = _parse_functions(target_source)
    new_fns: List[Dict[str, Any]] = []
    del_fns: List[Dict[str, Any]] = []
    sig_changed: List[Dict[str, Any]] = []
    body_changed: List[Dict[str, Any]] = []
    for key in sorted(set(tgt_fns) - set(base_fns)):
        rel, name = key
        new_fns.append({"name": name, "file": rel, "signature": tgt_fns[key]["signature"], "asil": tgt_fns[key]["asil"]})
    for key in sorted(set(base_fns) - set(tgt_fns)):
        rel, name = key
        del_fns.append({"name": name, "file": rel, "asil": base_fns[key]["asil"]})
    for key in sorted(set(base_fns) & set(tgt_fns)):
        rel, name = key
        b, t = base_fns[key], tgt_fns[key]
        # ASIL은 안전측 max 대신 '현재 값' 우선(target), 없으면 baseline 주석.
        asil = t["asil"] or b["asil"]
        if b["sig_norm"] != t["sig_norm"]:
            sig_changed.append({
                "name": name, "file": rel,
                "before": b["signature"], "after": t["signature"], "asil": asil,
            })
        elif b["body_norm"] != t["body_norm"]:
            body_changed.append({"name": name, "file": rel, "asil": asil})

    asil_touched = [
        {"name": r["name"], "file": r["file"], "asil": r["asil"], "change_kind": kind}
        for kind, rows in (("NEW", new_fns), ("DELETE", del_fns), ("SIGNATURE", sig_changed), ("BODY", body_changed))
        for r in rows
        if r.get("asil")
    ]

    return {
        "files": {
            "added": added,
            "deleted": deleted,
            "modified": modified,
            "unchanged": unchanged,
            "total_baseline": len(base_files),
            "total_target": len(tgt_files),
        },
        "functions": {
            "new": new_fns,
            "deleted": del_fns,
            "signature_changed": sig_changed,
            "body_changed": body_changed,
            "counts": {
                "new": len(new_fns), "deleted": len(del_fns),
                "signature": len(sig_changed), "body": len(body_changed),
            },
        },
        "asil_touched": asil_touched,
        "method": {
            "files": "relative-path join + sha1 (.c/.h)",
            "functions": "parse_c_project (파서 권위) — (file,함수명) 조인, signature/body 공백정규화 비교",
            "signature_before_after": "파서 signature 원문",
            "limitation": "파일 이동은 DELETE+NEW로 표시 · diff 텍스트 분류기는 함수 컨텍스트(-x -p) 부재로 미사용",
        },
        "computed_ms": int((time.time() - t0) * 1000),
    }
