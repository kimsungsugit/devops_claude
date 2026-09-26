"""소스 스냅샷에서 함수 1개의 본문·시그니처·의존을 회수(N4 — 케이스 초안 재료).

케이스 초안은 "소스에 실재하는 식별자만 인용"을 강제하므로 함수 본문이 필수다. 그런데
아키텍처 캐시는 핫스팟 상위 2개 발췌만 갖고 있고, 스냅샷 전체 파싱은 실측 2.8초/147파일이라
함수 하나를 위해 매번 돌릴 수 없다.

전략: ①함수명이 등장하는 소스 파일을 텍스트 스캔으로 좁히고(수십 ms) ②그 파일이 있는
**디렉터리만** parse_c_project로 파싱한다(파서 권위 유지, 비용은 전체의 일부). 다중 후보는
unit 힌트로 좁히고, 그래도 모호하면 ambiguous로 정직 반환한다(임의 선택 금지).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SRC_EXTS = {".c", ".h"}
_EXCLUDE_DIRS = {".svn", ".git"}
MAX_SCAN_FILES = 2000
MAX_DIR_PARSE_FILES = 80
EXCERPT_MAX_BYTES = 6000


def _candidate_files(source: Path, function: str) -> List[Path]:
    """함수 정의가 있을 법한 파일 — 이름 등장 + 정의 형태(뒤에 '(') 우선."""
    pat = re.compile(r"\b" + re.escape(function) + r"\s*\(")
    hits: List[Path] = []
    scanned = 0
    try:
        for p in source.rglob("*"):
            if scanned >= MAX_SCAN_FILES:
                break
            if not p.is_file() or p.suffix.lower() not in _SRC_EXTS:
                continue
            if any(seg in _EXCLUDE_DIRS for seg in p.parts):
                continue
            scanned += 1
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pat.search(text):
                hits.append(p)
    except OSError as exc:
        logger.debug("source scan failed (%s): %s", source, exc)
    # .c 우선(정의는 보통 .c에 있고 .h는 선언) — 순서만 조정, 후보는 유지한다.
    hits.sort(key=lambda p: (p.suffix.lower() != ".c", str(p)))
    return hits


def _narrow_by_unit(cands: List[Path], unit: Optional[str]) -> List[Path]:
    """unit 힌트(모듈명 또는 파일명)로 후보 축소 — 매칭 0이면 원본 유지(정보 손실 방지)."""
    u = str(unit or "").strip().lower()
    if not u:
        return cands
    u = u.split("'", 1)[0]                      # env 인스턴스 접미사 제거
    stem = u.rsplit(".", 1)[0]
    narrowed = [p for p in cands if p.stem.lower() == stem or stem in str(p).replace("\\", "/").lower()]
    return narrowed or cands


def lookup_function(build_root: Path, function: str, unit: Optional[str] = None) -> Dict[str, Any]:
    """함수 1개 회수. 반환 {ok, reason?, file, signature, body, params, globals, calls, asil}."""
    from workflow.code_parser.c_parser import parse_c_project

    name = str(function or "").strip()
    if not name:
        return {"ok": False, "reason": "function_required"}
    source = Path(build_root) / "source"
    if not source.is_dir():
        return {"ok": False, "reason": "snapshot_missing"}
    cands = _narrow_by_unit(_candidate_files(source, name), unit)
    if not cands:
        return {"ok": False, "reason": "function_not_found_in_snapshot"}

    # 후보 파일이 속한 디렉터리를 순서대로 파싱 — 첫 번째로 '정의'가 나온 곳을 채택한다.
    seen_dirs: set = set()
    for cand in cands[:5]:
        d = cand.parent
        if str(d) in seen_dirs:
            continue
        seen_dirs.add(str(d))
        try:
            parsed = parse_c_project(str(d), max_files=MAX_DIR_PARSE_FILES, preprocess=False)
        except Exception as exc:
            logger.debug("dir parse failed (%s): %s", d, exc)
            continue
        for f in parsed.get("functions") or []:
            if str(f.get("name") or "") != name:
                continue
            body = str(f.get("body") or "")
            rel = str(f.get("file") or "").replace("\\", "/")
            src_prefix = str(source.resolve()).replace("\\", "/").rstrip("/") + "/"
            if rel.lower().startswith(src_prefix.lower()):
                rel = rel[len(src_prefix):]
            return {
                "ok": True,
                "file": rel,
                "signature": str(f.get("signature") or ""),
                "body": body[:EXCERPT_MAX_BYTES],
                "body_truncated": len(body) > EXCERPT_MAX_BYTES,
                "params": [p for p in (f.get("comment_params") or []) if isinstance(p, dict)],
                "globals": [str(g) for g in (f.get("used_globals") or [])][:30],
                "calls": [str(c) for c in (f.get("calls") or [])][:30],
                "asil": (str(f.get("comment_asil") or "").strip() or None),
                "is_static": bool(f.get("is_static")),
                "doc": str(f.get("comment_desc") or "")[:500],
            }
    return {"ok": False, "reason": "function_definition_not_parsed",
            "candidates": [str(c.relative_to(source)).replace("\\", "/") for c in cands[:5]]}
