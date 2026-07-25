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
  주석이 없는 프로젝트를 위해 호출측이 요구 역전파 등급(asil_by_fn)을 주입할 수 있다(N2).
- v2(N3): 파일 행 아래 **변경 함수 목록**을 붙인 files.changed_detail — 여기에 함수별
  커버리지(주입)와 ASIL을 조인해 "이번 변화에서 재검증할 함수"를 한 화면에 낸다.
  기존 키(files.added/deleted/modified, functions.*)는 그대로 둔다(소비처 무손상).

정직성: 스냅샷 부재/단일 빌드는 reason으로 정직 실패. 비교 불가를 '변화 0'으로 위장하지 않는다.
커버리지/ASIL은 **주입식**이라 부재 시 None으로 남고(0%·QM으로 위장 금지), 조인 성립 수를
coverage_matched로 표면화한다.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# v2: files.changed_detail(파일→함수 롤업 + 커버리지/ASIL 조인) 추가 — 캐시 무효화용 bump.
BASELINE_DIFF_ALGO_VERSION = 2

# 표시 캡 — 대규모 리팩토링 스냅샷에서 응답이 폭증하지 않게. 절단은 항상 omitted로 표기한다.
MAX_DETAIL_FILES = 200
MAX_FUNCTIONS_PER_FILE = 40
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


_ASIL_ORDER = {"D": 4, "C": 3, "B": 2, "A": 1, "QM": 0}


def _resolve_asil(
    name: str, parsed_asil: Optional[str], asil_by_fn: Optional[Dict[str, Any]]
) -> Tuple[Optional[str], Optional[str]]:
    """(등급, 출처) — 주석 등급과 주입 등급(요구 역전파)의 안전측 병합.

    주입 맵은 `{정규화 함수명: {"asil","source"}}`(asil_propagation.merge_asil_sources 결과)
    또는 `{정규화 함수명: "D"}` 평면형 둘 다 받는다. 등급이 다르면 높은 쪽(안전측)을 쓴다.
    """
    from workflow.coverage_gap import _norm_fn

    injected = (asil_by_fn or {}).get(_norm_fn(name))
    inj_asil = injected.get("asil") if isinstance(injected, dict) else injected
    inj_src = injected.get("source") if isinstance(injected, dict) else "injected"
    a = str(parsed_asil or "").strip().upper() or None
    b = str(inj_asil or "").strip().upper() or None
    if a and b:
        if a == b:
            return a, "both"
        return (a, "comment_asil") if _ASIL_ORDER.get(a, -1) >= _ASIL_ORDER.get(b, -1) else (b, inj_src)
    if a:
        return a, "comment_asil"
    if b:
        return b, inj_src
    return None, None


def _build_changed_detail(
    file_rows: Dict[str, Dict[str, Any]],
    fn_rows: List[Dict[str, Any]],
    function_coverage: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """파일 행 × 변경 함수 → 파일별 트리 + 갭 요약. (rows, omitted, gap_summary).

    커버리지는 주입 맵 `{정규화 함수명: {statement, branch, ccn, metric_source}}`. 조인 실패는
    None으로 남기고 coverage_matched로 센다 — 미조인을 '커버 0%'로 위장하면 허위 경보가 된다.
    """
    from workflow.coverage_gap import _norm_fn

    cov = function_coverage or {}
    by_path: Dict[str, List[Dict[str, Any]]] = {}
    for r in fn_rows:
        by_path.setdefault(str(r.get("file") or ""), []).append(r)

    gap = {"changed_functions": len(fn_rows), "with_coverage": 0, "uncovered": 0,
           "below_full": 0, "asil_touched": 0, "coverage_unmatched": 0}
    rows: List[Dict[str, Any]] = []
    for path, meta in file_rows.items():
        fns = by_path.get(path) or []
        detail_fns: List[Dict[str, Any]] = []
        asil_max: Optional[str] = None
        worst: Optional[float] = None
        matched = 0
        for f in sorted(fns, key=lambda x: (str(x.get("kind")), str(x.get("name")))):
            c = cov.get(_norm_fn(f.get("name"))) or {}
            st = c.get("statement")
            br = c.get("branch")
            if c:
                matched += 1
                gap["with_coverage"] += 1
                if isinstance(st, (int, float)):
                    if st <= 0:
                        gap["uncovered"] += 1
                    elif st < 1.0:
                        gap["below_full"] += 1
                    worst = st if worst is None else min(worst, st)
            else:
                gap["coverage_unmatched"] += 1
            asil = f.get("asil")
            if asil:
                gap["asil_touched"] += 1
                if _ASIL_ORDER.get(str(asil), -1) > _ASIL_ORDER.get(str(asil_max or ""), -1):
                    asil_max = str(asil)
            detail_fns.append({
                "name": f.get("name"), "kind": f.get("kind"),
                "asil": asil, "asil_source": f.get("asil_source"),
                "before": f.get("before"), "after": f.get("after"),
                "statement": st, "branch": br, "ccn": c.get("ccn"),
                "metric_source": c.get("metric_source"),
            })
        counts = {"new": 0, "deleted": 0, "signature": 0, "body": 0}
        for f in fns:
            key = {"NEW": "new", "DELETE": "deleted", "SIGNATURE": "signature", "BODY": "body"}.get(str(f.get("kind")))
            if key:
                counts[key] += 1
        rows.append({
            "path": path,
            "change_kind": meta.get("change_kind"),
            "lines_added": meta.get("lines_added"),
            "lines_removed": meta.get("lines_removed"),
            "functions": detail_fns[:MAX_FUNCTIONS_PER_FILE],
            "functions_omitted": max(0, len(detail_fns) - MAX_FUNCTIONS_PER_FILE),
            "counts": counts,
            "asil_max": asil_max,
            "worst_statement": worst,
            "coverage_matched": matched,
        })
    # 위험 우선 정렬: ASIL 높은 순 → 커버리지 낮은 순(미조인은 뒤) → 변경 함수 많은 순 → 경로.
    rows.sort(key=lambda r: (
        -_ASIL_ORDER.get(str(r["asil_max"] or ""), -1),
        r["worst_statement"] if r["worst_statement"] is not None else 2.0,
        -sum(r["counts"].values()),
        r["path"],
    ))
    omitted = max(0, len(rows) - MAX_DETAIL_FILES)
    return rows[:MAX_DETAIL_FILES], omitted, gap


def compute_baseline_diff(
    *,
    baseline_source: Path,
    target_source: Path,
    function_coverage: Optional[Dict[str, Any]] = None,
    asil_by_fn: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """두 스냅샷 비교(순수 계산 — 캐시는 라우터). 파일 3분류 + 함수 파서 권위 분류.

    function_coverage / asil_by_fn은 주입식(라우터가 N1·N2 결과를 조립) — 서비스는 IO를 하지
    않는다. 부재 시 해당 컬럼은 None으로 남고 조인 성립 수만 표면화한다.
    """
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
        asil, src = _resolve_asil(name, tgt_fns[key]["asil"], asil_by_fn)
        new_fns.append({"name": name, "file": rel, "signature": tgt_fns[key]["signature"],
                        "asil": asil, "asil_source": src})
    for key in sorted(set(base_fns) - set(tgt_fns)):
        rel, name = key
        asil, src = _resolve_asil(name, base_fns[key]["asil"], asil_by_fn)
        del_fns.append({"name": name, "file": rel, "asil": asil, "asil_source": src})
    for key in sorted(set(base_fns) & set(tgt_fns)):
        rel, name = key
        b, t = base_fns[key], tgt_fns[key]
        # 주석 ASIL은 '현재 값' 우선(target), 없으면 baseline. 주입 등급과는 안전측 병합(_resolve_asil).
        asil, src = _resolve_asil(name, t["asil"] or b["asil"], asil_by_fn)
        if b["sig_norm"] != t["sig_norm"]:
            sig_changed.append({
                "name": name, "file": rel,
                "before": b["signature"], "after": t["signature"], "asil": asil, "asil_source": src,
            })
        elif b["body_norm"] != t["body_norm"]:
            body_changed.append({"name": name, "file": rel, "asil": asil, "asil_source": src})

    asil_touched = [
        {"name": r["name"], "file": r["file"], "asil": r["asil"], "change_kind": kind,
         "asil_source": r.get("asil_source")}
        for kind, rows in (("NEW", new_fns), ("DELETE", del_fns), ("SIGNATURE", sig_changed), ("BODY", body_changed))
        for r in rows
        if r.get("asil")
    ]

    # ── v2(N3): 파일 → 변경 함수 트리 ─────────────────────────────────────────
    file_rows: Dict[str, Dict[str, Any]] = {}
    for m in modified:
        file_rows[str(m["path"])] = {"change_kind": "modified",
                                     "lines_added": m["lines_added"], "lines_removed": m["lines_removed"]}
    for rel in added:
        file_rows[rel] = {"change_kind": "added", "lines_added": None, "lines_removed": None}
    for rel in deleted:
        file_rows[rel] = {"change_kind": "deleted", "lines_added": None, "lines_removed": None}
    fn_rows: List[Dict[str, Any]] = [
        {**r, "kind": kind}
        for kind, rows in (("NEW", new_fns), ("DELETE", del_fns), ("SIGNATURE", sig_changed), ("BODY", body_changed))
        for r in rows
    ]
    changed_detail, detail_omitted, gap_summary = _build_changed_detail(file_rows, fn_rows, function_coverage)

    return {
        "files": {
            "added": added,
            "deleted": deleted,
            "modified": modified,
            "unchanged": unchanged,
            "total_baseline": len(base_files),
            "total_target": len(tgt_files),
            # 파일 행 아래 변경 함수를 붙인 트리(위험 우선 정렬) — 기존 키와 병존.
            "changed_detail": changed_detail,
            "changed_detail_omitted": detail_omitted,
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
            # 변경 함수 × 커버리지/ASIL 갭 요약 — '이번 변화에서 재검증할 것' 최상위 신호.
            "gap_summary": gap_summary,
        },
        "asil_touched": asil_touched,
        "coverage_join": {
            "injected": bool(function_coverage),
            "functions_in_index": len(function_coverage or {}),
            "matched": gap_summary["with_coverage"],
            "unmatched": gap_summary["coverage_unmatched"],
        },
        "asil_join": {"injected": bool(asil_by_fn), "functions_in_index": len(asil_by_fn or {})},
        "method": {
            "files": "relative-path join + sha1 (.c/.h)",
            "functions": "parse_c_project (파서 권위) — (file,함수명) 조인, signature/body 공백정규화 비교",
            "signature_before_after": "파서 signature 원문",
            "coverage": "주입식 함수 커버리지 인덱스와 함수명 정규화 조인 — 미조인은 null(0% 아님)",
            "asil": "주석 @asil + 주입 등급(요구 역전파) 안전측 병합 — 출처는 asil_source",
            "limitation": "파일 이동은 DELETE+NEW로 표시 · diff 텍스트 분류기는 함수 컨텍스트(-x -p) 부재로 미사용",
        },
        "computed_ms": int((time.time() - t0) * 1000),
    }
