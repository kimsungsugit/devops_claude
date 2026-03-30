from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from time import time
import xml.etree.ElementTree as ET
import config

# 리포트 파일 목록 캐시
_report_files_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
_REPORT_FILES_CACHE_TTL = float(getattr(config, "REPORT_FILES_CACHE_TTL", 10.0))


def read_text_limited(path: Path, max_bytes: int) -> Tuple[str, bool]:
    try:
        raw = path.read_bytes()
    except Exception:
        return "", False
    truncated = False
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
        truncated = True
    return raw.decode("utf-8", errors="ignore"), truncated


def tail_text(path: Path, max_bytes: int = 512 * 1024) -> str:
    try:
        size = int(path.stat().st_size)
    except Exception:
        size = 0
    try:
        with path.open("rb") as f:
            if size > int(max_bytes):
                f.seek(size - int(max_bytes))
            data = f.read(int(max_bytes))
        return data.decode("utf-8", errors="ignore")
    except Exception:
        try:
            return path.read_text(errors="ignore")[:200000]
        except Exception:
            return ""


def read_csv_rows(path: Path, limit: int = 5000) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                if idx >= limit:
                    break
                rows.append({k: v for k, v in row.items()})
    except Exception:
        return []
    return rows


def normalize_rate_0_1(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        v = float(value)
    except Exception:
        return None
    if v <= 1.0:
        return v
    if v <= 100.0:
        return v / 100.0
    if v <= 10000.0:
        return v / 10000.0
    return v


def _candidate_coverage_paths(root: Path) -> List[Path]:
    return [
        root / "coverage" / "coverage.xml",
        root / "coverage.xml",
    ]


def parse_coverage_xml(roots: Iterable[Path]) -> Optional[Dict[str, Any]]:
    candidates: List[Path] = []
    for root in roots:
        if not root or not Path(root).exists():
            continue
        for cand in _candidate_coverage_paths(Path(root)):
            if cand.exists():
                candidates.append(cand)
        if candidates:
            break
        try:
            for idx, cand in enumerate(Path(root).rglob("coverage.xml")):
                if cand.is_file():
                    candidates.append(cand)
                if idx >= 20:
                    break
        except Exception:
            continue
        if candidates:
            break
    if not candidates:
        return None
    try:
        xml_path = candidates[0]
        root = ET.parse(xml_path).getroot()
        line_rate = normalize_rate_0_1(root.attrib.get("line-rate") or root.attrib.get("line_rate"))
        branch_rate = normalize_rate_0_1(root.attrib.get("branch-rate") or root.attrib.get("branch_rate"))
        return {
            "path": str(xml_path),
            "line_rate": line_rate,
            "branch_rate": branch_rate,
        }
    except Exception:
        return None


def list_log_candidates(report_dir: Path) -> Dict[str, List[Path]]:
    candidates: Dict[str, List[Path]] = {"system": [], "asan": [], "fuzz": [], "qemu": [], "ctest": [], "lizard": []}
    report_dir = Path(report_dir)
    system_log = report_dir / "system.log"
    if system_log.exists():
        candidates["system"].append(system_log)
    lizard_log = report_dir / "lizard_audit.log"
    if lizard_log.exists():
        candidates["lizard"].append(lizard_log)
    tests_dir = report_dir / "tests"
    if tests_dir.exists():
        for p in tests_dir.glob("*.txt"):
            if "ctest" in p.name.lower():
                candidates["ctest"].append(p)
    for pat in ["*asan*.log", "*asan*.txt", "*ASAN*.log", "*ASAN*.txt"]:
        candidates["asan"] += list(report_dir.glob(pat))
    for pat in ["*fuzz*.log", "*fuzz*.txt", "*FUZZ*.log", "*FUZZ*.txt"]:
        candidates["fuzz"] += list(report_dir.glob(pat))
    for pat in ["*qemu*.log", "*qemu*.txt", "*QEMU*.log", "*QEMU*.txt"]:
        candidates["qemu"] += list(report_dir.glob(pat))
    fuzz_dir = report_dir / "fuzz"
    if fuzz_dir.exists():
        candidates["fuzz"] += list(fuzz_dir.glob("**/*.log"))
        candidates["fuzz"] += list(fuzz_dir.glob("**/*.txt"))
    qemu_dir = report_dir / "qemu"
    if qemu_dir.exists():
        candidates["qemu"] += list(qemu_dir.glob("**/*.log"))
        candidates["qemu"] += list(qemu_dir.glob("**/*.txt"))
    for k in candidates:
        uniq = sorted({p.resolve() for p in candidates[k]})
        candidates[k] = uniq
    return candidates


def _normalize_filter_tokens(values: Optional[List[str]]) -> List[str]:
    if not values:
        return []
    out: List[str] = []
    for item in values:
        raw = str(item).replace("\\", "/").strip().strip("/")
        if raw:
            out.append(raw)
    return out


def _matches_filters(rel_path: str, include: List[str], exclude: List[str]) -> bool:
    rel_norm = rel_path.replace("\\", "/").strip("/")
    if exclude:
        for token in exclude:
            if rel_norm == token or rel_norm.startswith(f"{token}/"):
                return False
    if include:
        for token in include:
            if rel_norm == token or rel_norm.startswith(f"{token}/"):
                return True
        return False
    return True


def list_report_files(
    base_dir: Path,
    limit: int = 2000,
    include_paths: Optional[List[str]] = None,
    exclude_paths: Optional[List[str]] = None,
    dedupe: Optional[str] = None,
) -> Dict[str, Any]:
    base_dir = Path(base_dir).resolve()
    include_tokens = _normalize_filter_tokens(include_paths)
    exclude_tokens = _normalize_filter_tokens(exclude_paths)
    cache_key = f"{str(base_dir)}:{limit}:{dedupe}:{','.join(include_tokens)}:{','.join(exclude_tokens)}"
    current_time = time()
    
    # 캐시 확인
    if cache_key in _report_files_cache:
        cached_data, cache_time = _report_files_cache[cache_key]
        if current_time - cache_time < _REPORT_FILES_CACHE_TTL:
            return cached_data
    
    files: List[Dict[str, Any]] = []
    ext_counts: Dict[str, int] = {}
    seen: set[str] = set()
    if not base_dir.exists():
        result = {"files": files, "ext_counts": ext_counts}
        _report_files_cache[cache_key] = (result, current_time)
        return result
    
    for idx, path in enumerate(base_dir.rglob("*")):
        if idx >= limit:
            break
        if not path.is_file():
            continue
        try:
            rel = str(path.relative_to(base_dir)).replace("\\", "/")
            if not _matches_filters(rel, include_tokens, exclude_tokens):
                continue
            stat = path.stat()
            ext = path.suffix.lower().lstrip(".") or "no_ext"
            size = int(stat.st_size)
            if dedupe == "name_size":
                key = f"{path.name.lower()}::{size}"
                if key in seen:
                    continue
                seen.add(key)
            elif dedupe == "rel_path":
                key = rel.lower()
                if key in seen:
                    continue
                seen.add(key)
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            files.append(
                {
                    "rel_path": rel,
                    "path": str(path),
                    "ext": ext,
                    "size": size,
                    "mtime": stat.st_mtime,
                }
            )
        except Exception:
            continue
    files.sort(key=lambda x: x.get("rel_path", ""))
    result = {"files": files, "ext_counts": ext_counts}
    
    # 캐시 저장
    _report_files_cache[cache_key] = (result, current_time)
    return result


def invalidate_report_files_cache(base_dir: Optional[Path] = None) -> None:
    """리포트 파일 목록 캐시 무효화"""
    if base_dir:
        cache_key_prefix = str(Path(base_dir).resolve())
        keys_to_remove = [k for k in _report_files_cache.keys() if k.startswith(cache_key_prefix)]
        for key in keys_to_remove:
            _report_files_cache.pop(key, None)
    else:
        _report_files_cache.clear()
