from __future__ import annotations

import json
import re
from datetime import datetime
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import config
from backend.services.files import list_report_files

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - optional dependency
    BeautifulSoup = None  # type: ignore

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional dependency
    pd = None  # type: ignore


def read_json(path: Path, default: Any = None) -> Any:
    if not path or not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def find_first(root_dir: Path, filename: str) -> Optional[Path]:
    try:
        for cand in root_dir.rglob(filename):
            if cand.is_file():
                return cand
    except Exception:
        return None
    return None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _parse_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    if raw.endswith("%"):
        raw = raw[:-1].strip()
    try:
        return float(raw)
    except Exception:
        return None


def parse_html_report(path: Path) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"path": str(path), "title": None, "tables": [], "headings": []}
    if not path.exists():
        summary["error"] = "missing_file"
        return summary
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        summary["error"] = "read_failed"
        return summary
    if not BeautifulSoup:
        summary["error"] = "bs4_missing"
        return summary
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.string if soup.title else ""
    summary["title"] = _clean_text(title) or None
    headings = []
    for node in soup.find_all(["h1", "h2"], limit=6):
        txt = _clean_text(node.get_text(" ", strip=True))
        if txt:
            headings.append(txt)
    summary["headings"] = headings
    tables: List[Dict[str, str]] = []
    for table in soup.find_all("table")[:3]:
        rows: Dict[str, str] = {}
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) >= 2:
                key = _clean_text(cells[0])
                val = _clean_text(cells[1])
                if key and key not in rows:
                    rows[key] = val
            if len(rows) >= 12:
                break
        if rows:
            tables.append(rows)
    summary["tables"] = tables
    return summary


def extract_table_metrics(tables: List[Dict[str, str]], keys: Iterable[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for table in tables:
        for key in keys:
            if key in table and key not in out:
                out[key] = table[key]
    return out


def parse_prqa_rcr_summary(path: Path) -> Dict[str, Any]:
    data = parse_html_report(path)
    tables = data.get("tables") or []
    metrics = extract_table_metrics(
        tables,
        [
            "Number of Files",
            "Lines of Code (source files only)",
            "Diagnostic Count",
            "Rule Violation Count",
            "Violated Rules",
            "Compliant Rules",
            "File Compliance Index",
            "Project Compliance Index",
        ],
    )
    normalized: Dict[str, Any] = {}
    for key, val in metrics.items():
        num = _parse_number(val)
        normalized[key] = num if num is not None else val
    return {
        "path": str(path),
        "metrics": normalized,
    }


def _parse_table_matrix(table: Any) -> Tuple[List[str], List[List[str]], List[List[Dict[str, str]]]]:
    headers: List[str] = []
    rows: List[List[str]] = []
    meta_rows: List[List[Dict[str, str]]] = []
    if not table:
        return headers, rows, meta_rows
    head = table.find("tr")
    if head:
        headers = [_clean_text(th.get_text(" ", strip=True)) for th in head.find_all(["th", "td"])]
    for tr in table.find_all("tr")[1:]:
        cells = []
        meta_cells: List[Dict[str, str]] = []
        for td in tr.find_all(["td", "th"]):
            cells.append(_clean_text(td.get_text(" ", strip=True)))
            link = td.find("a")
            meta_cells.append(
                {
                    "href": link.get("href") if link else "",
                    "title": link.get("title") if link else "",
                }
            )
        if cells:
            rows.append(cells)
            meta_rows.append(meta_cells)
    return headers, rows, meta_rows


def _apply_mapping_rules(value: str, job_slug: Optional[str], rules: List[Dict[str, Any]]) -> str:
    raw = str(value).replace("\\", "/")
    for rule in rules or []:
        src = str(rule.get("from") or "").replace("\\", "/")
        dst = str(rule.get("to") or "").replace("\\", "/")
        if not src or not dst:
            continue
        if job_slug:
            src = src.replace("{job}", job_slug).replace("<job>", job_slug)
            dst = dst.replace("{job}", job_slug).replace("<job>", job_slug)
        if raw.startswith(src):
            return raw.replace(src, dst, 1)
    return raw


def _normalize_prqa_path(value: str, project_root: Optional[Path], job_slug: Optional[str]) -> str:
    if not value:
        return ""
    raw = _apply_mapping_rules(value, job_slug, getattr(config, "PRQA_PATH_MAPPINGS", []) or [])
    raw = _apply_mapping_rules(raw, job_slug, getattr(config, "JENKINS_PATH_MAPPINGS", []) or [])
    return _normalize_report_path(raw, project_root, job_slug)


def _normalize_report_path(value: str, project_root: Optional[Path], job_slug: Optional[str]) -> str:
    raw = str(value or "").replace("\\", "/")
    if not raw:
        return ""
    raw = _apply_mapping_rules(raw, job_slug, getattr(config, "JENKINS_PATH_MAPPINGS", []) or [])
    if re.match(r"^[A-Za-z]:/", raw):
        abs_path = Path(raw)
        if abs_path.exists():
            return str(abs_path)
    if not project_root:
        return raw
    for marker in ("/source/", "/Sources/"):
        if marker in raw:
            tail = raw.split(marker, 1)[1]
            cand = (Path(project_root) / tail).resolve()
            if cand.exists():
                return str(cand)
    return raw


def parse_prqa_rcr_details(
    path: Path,
    top_n: int = 6,
    project_root: Optional[Path] = None,
    job_slug: Optional[str] = None,
) -> Dict[str, Any]:
    data = parse_html_report(path)
    if "error" in data:
        return {"path": str(path), "error": data["error"]}
    if not BeautifulSoup:
        return {"path": str(path), "error": "bs4_missing"}
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {"path": str(path), "error": "read_failed"}
    soup = BeautifulSoup(raw, "html.parser")
    def _find_table(anchor: str) -> Any:
        node = soup.find(attrs={"name": anchor}) or soup.find(id=anchor)
        if not node:
            return None
        return node.find_next("table")

    worst_rules_table = _find_table("WorstRules")
    file_status_table = _find_table("FileStatus")
    worst_headers, worst_rows, _ = _parse_table_matrix(worst_rules_table)
    file_headers, file_rows, file_meta = _parse_table_matrix(file_status_table)

    top_rules: List[Dict[str, Any]] = []
    if worst_headers and "Files" in worst_headers:
        idx_files = worst_headers.index("Files")
        rule_totals: Dict[str, float] = {}
        for row in worst_rows:
            for idx, header in enumerate(worst_headers):
                if idx == idx_files or idx >= len(row):
                    continue
                val = _parse_number(row[idx]) or 0
                rule_totals[header] = rule_totals.get(header, 0) + val
        top_rules = [
            {"rule": key, "count": rule_totals[key]}
            for key in sorted(rule_totals, key=lambda k: rule_totals[k], reverse=True)[:top_n]
        ]

    top_files: List[Dict[str, Any]] = []
    if file_headers:
        def _idx(name: str) -> Optional[int]:
            for idx, h in enumerate(file_headers):
                if name.lower() in h.lower():
                    return idx
            return None
        idx_file = _idx("File")
        idx_violation = _idx("Violation Count") or _idx("Violations") or _idx("Diagnostic Count")
        if idx_file is not None and idx_violation is not None:
            rows: List[Tuple[float, str, Dict[str, str]]] = []
            for row_idx, row in enumerate(file_rows):
                if idx_file >= len(row) or idx_violation >= len(row):
                    continue
                score = _parse_number(row[idx_violation]) or 0
                meta = {}
                if row_idx < len(file_meta) and idx_file < len(file_meta[row_idx]):
                    meta = file_meta[row_idx][idx_file]
                rows.append((score, row[idx_file], meta))
            rows.sort(key=lambda x: x[0], reverse=True)
            top_files = []
            for score, name, meta in rows[:top_n]:
                normalized_path = _normalize_prqa_path(meta.get("title") or meta.get("href") or "", project_root, job_slug)
                top_files.append(
                    {
                        "file": name,
                        "count": score,
                        "path": normalized_path,
                    }
                )
    return {"path": str(path), "top_rules": top_rules, "top_files": top_files}


def parse_vectorcast_metrics_summary(path: Path) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"path": str(path), "avg_pct": None, "samples": 0}
    if not path.exists():
        summary["error"] = "missing_file"
        return summary
    if not BeautifulSoup:
        summary["error"] = "bs4_missing"
        return summary
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        summary["error"] = "read_failed"
        return summary
    soup = BeautifulSoup(raw, "html.parser")
    values: List[float] = []
    for td in soup.find_all("td"):
        classes = " ".join(td.get("class") or [])
        if "col_metric" not in classes:
            continue
        text = td.get_text(" ", strip=True)
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if match:
            values.append(float(match.group(1)))
    if values:
        summary["avg_pct"] = round(sum(values) / len(values), 2)
        summary["samples"] = len(values)
    return summary


def parse_vectorcast_aggregate_summary(path: Path, top_n: int = 6) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "path": str(path),
        "line_rate": None,
        "branch_rate": None,
        "line_total": 0,
        "line_covered": 0,
        "branch_total": 0,
        "branch_covered": 0,
        "modules": [],
    }
    if not path.exists():
        summary["error"] = "missing_file"
        return summary
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        summary["error"] = "read_failed"
        return summary
    line_total = 0
    line_cov = 0
    branch_total = 0
    branch_cov = 0
    modules: List[Dict[str, Any]] = []
    parts = re.split(r"Code Coverage for\s+", text)
    for part in parts[1:]:
        name_match = re.match(r"([^<\n]+)", part)
        if not name_match:
            continue
        name = _clean_text(name_match.group(1))
        line_match = re.search(r"(\d+)\s+of\s+(\d+)\s+Lines Covered", part)
        branch_match = re.search(r"(\d+)\s+of\s+(\d+)\s+Branches Covered", part)
        if line_match:
            line_cov += int(line_match.group(1))
            line_total += int(line_match.group(2))
        if branch_match:
            branch_cov += int(branch_match.group(1))
            branch_total += int(branch_match.group(2))
        module = {"name": name}
        if line_match:
            module["line_rate"] = round((int(line_match.group(1)) / int(line_match.group(2))) * 100, 2)
        if branch_match:
            module["branch_rate"] = round((int(branch_match.group(1)) / int(branch_match.group(2))) * 100, 2)
        if line_match or branch_match:
            modules.append(module)
    summary["line_total"] = line_total
    summary["line_covered"] = line_cov
    summary["branch_total"] = branch_total
    summary["branch_covered"] = branch_cov
    if line_total:
        summary["line_rate"] = round((line_cov / line_total) * 100, 2)
    if branch_total:
        summary["branch_rate"] = round((branch_cov / branch_total) * 100, 2)
    if modules:
        modules.sort(key=lambda m: (m.get("line_rate") or 0))
        summary["modules"] = modules[:top_n]
    return summary


def parse_xlsx_report(path: Path) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"path": str(path), "sheets": [], "rows": 0, "columns": []}
    if not path.exists():
        summary["error"] = "missing_file"
        return summary
    if pd is None:
        summary["error"] = "pandas_missing"
        return summary
    try:
        xls = pd.ExcelFile(path)
        summary["sheets"] = list(xls.sheet_names)
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])
        summary["rows"] = int(len(df.index))
        summary["columns"] = [str(c) for c in list(df.columns)[:12]]
        for col in df.columns:
            name = str(col).lower()
            if "violation" in name or "violations" in name:
                try:
                    summary["violations_total"] = int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())
                except Exception:
                    pass
        return summary
    except Exception:
        summary["error"] = "parse_failed"
        return summary


def parse_json_report(path: Path) -> Dict[str, Any]:
    data = read_json(path, default={})
    if not isinstance(data, dict):
        return {"path": str(path), "error": "invalid_json"}
    keys = list(data.keys())
    return {"path": str(path), "keys": keys[:20], "size": len(keys)}


def _collect_files(root_dir: Path, summary_mode: bool = False) -> Dict[str, Any]:
    if summary_mode:
        data = list_report_files(
            root_dir,
            exclude_paths=["jenkins_scan_export", "exports"],
            dedupe="name_size",
        )
    else:
        data = list_report_files(root_dir)
    files = data.get("files") or []
    ext_counts = data.get("ext_counts") or {}
    return {"files": files, "ext_counts": ext_counts}


def _extract_scan_kpis(scan: Dict[str, Any]) -> Dict[str, Any]:
    if not scan or not isinstance(scan, dict):
        return {}
    summary = scan.get("summary") or scan
    return {
        "files_total": summary.get("files_total"),
        "html_count": summary.get("html_count"),
        "xlsx_count": summary.get("xlsx_count"),
        "log_count": summary.get("log_count"),
        "fail": summary.get("FAIL_token"),
        "error": summary.get("ERROR_token"),
        "warn": summary.get("WARN_token"),
    }


def _top_scan_files(scan: Dict[str, Any], limit: int = 6) -> List[Dict[str, Any]]:
    kpis = scan.get("kpis_by_file") if isinstance(scan, dict) else None
    if not isinstance(kpis, dict):
        return []
    rows: List[Tuple[int, str, Dict[str, Any]]] = []
    for path, metrics in kpis.items():
        if not isinstance(metrics, dict):
            continue
        score = int(metrics.get("FAIL_token", 0)) * 5 + int(metrics.get("ERROR_token", 0)) * 3 + int(metrics.get("WARN_token", 0))
        if score <= 0:
            continue
        rows.append((score, path, metrics))
    rows.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "path": path,
            "fail": metrics.get("FAIL_token", 0),
            "error": metrics.get("ERROR_token", 0),
            "warn": metrics.get("WARN_token", 0),
        }
        for _, path, metrics in rows[:limit]
    ]


def _report_name_from_dir(root_dir: Path) -> str:
    name = root_dir.name
    if name.lower() == "report":
        return "Local Report"
    return name


def _report_timestamp_from_dir(root_dir: Path) -> Optional[str]:
    match = re.search(r"(\d{8}_\d{6})", root_dir.name)
    if not match:
        return None
    return match.group(1)


def _job_slug_from_dir(root_dir: Path) -> Optional[str]:
    if not root_dir.name.startswith("jenkins_reports_"):
        return None
    raw = root_dir.name[len("jenkins_reports_") :]
    match = re.search(r"(.+)_\d{8}_\d{6}$", raw)
    if match:
        return match.group(1)
    return raw or None


def _classify_report_type(path: str, title: Optional[str] = None) -> str:
    name = Path(path).name.lower()
    title_s = (title or "").lower()
    if "rule compliance report" in title_s or "_rcr_" in name:
        return "prqa_rcr"
    if "code review report" in title_s or "_crr_" in name:
        return "prqa_crr"
    if "his metrics report" in title_s or "_hmr_" in name:
        return "prqa_hmr"
    if "aggregate report" in title_s or "aggregate_report" in name:
        return "vcast_aggregate"
    if "metrics report" in title_s or "metrics_report" in name:
        return "vcast_metrics"
    if "environment_report" in name:
        return "vcast_environment"
    if "full_report" in name:
        return "vcast_full"
    if "vectorcast" in name or "vcast" in name:
        return "vcast_other"
    if name.endswith(".xlsx"):
        return "xlsx"
    if name.endswith(".json"):
        return "json"
    if name.endswith(".log"):
        return "log"
    return "other"


def classify_report_group(path: str, title: Optional[str] = None) -> str:
    kind = _classify_report_type(path, title)
    if kind.startswith("prqa"):
        return "prqa"
    if kind.startswith("vcast") or kind.startswith("vectorcast"):
        return "vectorcast"
    if kind in ("xlsx", "json", "log"):
        return kind
    return "other"


def _extract_build_info(summary: Dict[str, Any], status: Dict[str, Any]) -> Dict[str, Any]:
    jenkins = summary.get("jenkins") if isinstance(summary, dict) else {}
    return {
        "job_url": (jenkins or {}).get("job_url") or status.get("job_url"),
        "build_number": (jenkins or {}).get("build_number") or status.get("build_number"),
        "result": (jenkins or {}).get("result") or status.get("result") or status.get("status"),
        "build_url": (jenkins or {}).get("build_url") or status.get("build_url"),
        "timestamp": status.get("timestamp"),
        "failure_stage": status.get("failure_stage"),
    }


def build_report_summary(root_dir: Path, project_root: Optional[Path] = None) -> Dict[str, Any]:
    root_dir = Path(root_dir).resolve()
    project_root = Path(project_root).resolve() if project_root else None
    files_meta = _collect_files(root_dir, summary_mode=True)
    files = files_meta.get("files", [])
    ext_counts = files_meta.get("ext_counts", {})

    analysis_summary_path = find_first(root_dir, "analysis_summary.json")
    status_path = find_first(root_dir, "status.json")
    jenkins_scan_path = find_first(root_dir, "jenkins_scan.json")
    vectorcast_rag_path = find_first(root_dir, "vectorcast_rag.json")

    analysis_summary = read_json(analysis_summary_path, {}) if analysis_summary_path else {}
    status = read_json(status_path, {}) if status_path else {}
    jenkins_scan = read_json(jenkins_scan_path, {}) if jenkins_scan_path else {}
    vectorcast_rag = read_json(vectorcast_rag_path, {}) if vectorcast_rag_path else {}

    coverage = analysis_summary.get("coverage") if isinstance(analysis_summary, dict) else {}
    if not isinstance(coverage, dict):
        coverage = {}
    tests = analysis_summary.get("tests") if isinstance(analysis_summary, dict) else {}
    if not isinstance(tests, dict):
        tests = {}

    html_files = [item for item in files if item.get("ext") == "html"]
    xlsx_files = [item for item in files if item.get("ext") == "xlsx"]
    json_files = [item for item in files if item.get("ext") == "json"]

    parsed_html = [
        parse_html_report(root_dir / item["rel_path"])
        for item in html_files[:6]
        if item.get("rel_path")
    ]
    parsed_xlsx = [
        parse_xlsx_report(root_dir / item["rel_path"])
        for item in xlsx_files[:3]
        if item.get("rel_path")
    ]
    parsed_json = [
        parse_json_report(root_dir / item["rel_path"])
        for item in json_files[:5]
        if item.get("rel_path")
    ]

    report_types: Dict[str, int] = {}
    for item in html_files:
        rel = item.get("rel_path")
        if not rel:
            continue
        parsed = parse_html_report(root_dir / rel)
        kind = _classify_report_type(rel, parsed.get("title"))
        report_types[kind] = report_types.get(kind, 0) + 1
    for item in xlsx_files:
        rel = item.get("rel_path")
        if not rel:
            continue
        kind = _classify_report_type(rel)
        report_types[kind] = report_types.get(kind, 0) + 1
    for item in json_files:
        rel = item.get("rel_path")
        if not rel:
            continue
        kind = _classify_report_type(rel)
        report_types[kind] = report_types.get(kind, 0) + 1

    build_info = _extract_build_info(analysis_summary, status)
    scan_kpis = _extract_scan_kpis(jenkins_scan)
    top_scan_files = _top_scan_files(jenkins_scan)

    prqa_rcr_path = next((root_dir / item["rel_path"] for item in html_files if "_RCR_" in item.get("rel_path", "")), None)
    job_slug = _job_slug_from_dir(root_dir)
    prqa_rcr = parse_prqa_rcr_summary(prqa_rcr_path) if prqa_rcr_path else {}
    prqa_rcr_details = parse_prqa_rcr_details(
        prqa_rcr_path,
        project_root=project_root,
        job_slug=job_slug,
    ) if prqa_rcr_path else {}
    prqa_metrics = prqa_rcr.get("metrics", {}) if isinstance(prqa_rcr, dict) else {}
    prqa_hmr_path = next((root_dir / item["rel_path"] for item in xlsx_files if "_HMR_" in item.get("rel_path", "")), None)
    prqa_hmr = parse_xlsx_report(prqa_hmr_path) if prqa_hmr_path else {}

    vcast_metrics_path = next((root_dir / item["rel_path"] for item in html_files if "metrics_report" in item.get("rel_path", "").lower()), None)
    vcast_metrics = parse_vectorcast_metrics_summary(vcast_metrics_path) if vcast_metrics_path else {}
    vcast_ut_aggregate = next((root_dir / item["rel_path"] for item in html_files if "aggregate_report" in item.get("rel_path", "").lower() and "_UT_" in item.get("rel_path", "")), None)
    vcast_it_aggregate = next((root_dir / item["rel_path"] for item in html_files if "aggregate_report" in item.get("rel_path", "").lower() and "_IT_" in item.get("rel_path", "")), None)
    vcast_ut_summary = parse_vectorcast_aggregate_summary(vcast_ut_aggregate) if vcast_ut_aggregate else {}
    vcast_it_summary = parse_vectorcast_aggregate_summary(vcast_it_aggregate) if vcast_it_aggregate else {}

    safe_coverage = coverage if isinstance(coverage, dict) else {}
    safe_tests = tests if isinstance(tests, dict) else {}

    summary: Dict[str, Any] = {
        "source": {
            "name": _report_name_from_dir(root_dir),
            "path": str(root_dir),
            "timestamp": _report_timestamp_from_dir(root_dir),
            "job_slug": job_slug,
        },
        "kpis": {
            "build": build_info,
            "coverage": {
                "line_rate": safe_coverage.get("line_rate"),
                "branch_rate": safe_coverage.get("branch_rate"),
                "ok": safe_coverage.get("ok"),
                "threshold": safe_coverage.get("threshold"),
            },
            "tests": {
                "ok": safe_tests.get("ok"),
                "total": safe_tests.get("total") or safe_tests.get("count"),
                "enabled": safe_tests.get("enabled"),
            },
            "scan": scan_kpis,
            "files": ext_counts,
            "prqa": {
                "rule_violation_count": prqa_metrics.get("Rule Violation Count"),
                "violated_rules": prqa_metrics.get("Violated Rules"),
                "compliant_rules": prqa_metrics.get("Compliant Rules"),
                "diagnostic_count": prqa_metrics.get("Diagnostic Count"),
                "file_compliance_index": prqa_metrics.get("File Compliance Index"),
                "project_compliance_index": prqa_metrics.get("Project Compliance Index"),
                "xlsx_rows": prqa_hmr.get("rows") if isinstance(prqa_hmr, dict) else None,
                "xlsx_violations_total": prqa_hmr.get("violations_total") if isinstance(prqa_hmr, dict) else None,
                "top_rules": prqa_rcr_details.get("top_rules") if isinstance(prqa_rcr_details, dict) else [],
                "top_files": prqa_rcr_details.get("top_files") if isinstance(prqa_rcr_details, dict) else [],
            },
            "vectorcast": {
                "metrics_avg_pct": vcast_metrics.get("avg_pct") if isinstance(vcast_metrics, dict) else None,
                "metrics_samples": vcast_metrics.get("samples") if isinstance(vcast_metrics, dict) else None,
                "ut": vcast_ut_summary,
                "it": vcast_it_summary,
            },
        },
        "developer": {
            "top_scan_files": top_scan_files,
            "warnings_total": scan_kpis.get("warn"),
            "errors_total": scan_kpis.get("error"),
            "fail_total": scan_kpis.get("fail"),
            "prqa_rule_violations": prqa_metrics.get("Rule Violation Count"),
            "vectorcast_metrics_avg_pct": vcast_metrics.get("avg_pct") if isinstance(vcast_metrics, dict) else None,
            "prqa_top_rules": prqa_rcr_details.get("top_rules") if isinstance(prqa_rcr_details, dict) else [],
            "prqa_top_files": prqa_rcr_details.get("top_files") if isinstance(prqa_rcr_details, dict) else [],
        },
        "tester": {
            "vectorcast": {
                "ut_reports": vectorcast_rag.get("ut_reports", []) if isinstance(vectorcast_rag, dict) else [],
                "it_reports": vectorcast_rag.get("it_reports", []) if isinstance(vectorcast_rag, dict) else [],
                "test_rows_count": vectorcast_rag.get("test_rows_count") if isinstance(vectorcast_rag, dict) else None,
                "testcase_details_count": vectorcast_rag.get("testcase_details_count") if isinstance(vectorcast_rag, dict) else None,
            },
            "coverage_line": coverage.get("line_rate"),
            "vectorcast_metrics_avg_pct": vcast_metrics.get("avg_pct") if isinstance(vcast_metrics, dict) else None,
            "vectorcast_ut_line_rate": vcast_ut_summary.get("line_rate") if isinstance(vcast_ut_summary, dict) else None,
            "vectorcast_ut_branch_rate": vcast_ut_summary.get("branch_rate") if isinstance(vcast_ut_summary, dict) else None,
            "vectorcast_it_line_rate": vcast_it_summary.get("line_rate") if isinstance(vcast_it_summary, dict) else None,
            "vectorcast_it_branch_rate": vcast_it_summary.get("branch_rate") if isinstance(vcast_it_summary, dict) else None,
        },
        "manager": {
            "result": build_info.get("result"),
            "failure_stage": build_info.get("failure_stage"),
            "files_total": scan_kpis.get("files_total"),
            "prqa_project_compliance_index": prqa_metrics.get("Project Compliance Index"),
            "vectorcast_ut_line_rate": vcast_ut_summary.get("line_rate") if isinstance(vcast_ut_summary, dict) else None,
            "vectorcast_it_line_rate": vcast_it_summary.get("line_rate") if isinstance(vcast_it_summary, dict) else None,
        },
        "artifacts": {
            "html": parsed_html,
            "xlsx": parsed_xlsx,
            "json": parsed_json,
        },
        "report_types": report_types,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return summary


def find_project_report_dirs(base_dir: Path) -> List[Path]:
    base_dir = Path(base_dir).resolve()
    roots: List[Path] = []
    report_dir = base_dir / "Report"
    if report_dir.exists():
        roots.append(report_dir)
    for cand in base_dir.glob("jenkins_reports_*"):
        if cand.is_dir():
            roots.append(cand)
    return roots


def find_local_jenkins_report_dir(base_dir: Path, job_slug: str) -> Optional[Path]:
    base_dir = Path(base_dir).resolve()
    candidates = [p for p in base_dir.glob(f"jenkins_reports_{job_slug}*") if p.is_dir()]
    if not candidates:
        return None
    def _ts_key(path: Path) -> str:
        match = re.search(r"\d{8}_\d{6}", path.name)
        return match.group(0) if match else ""
    candidates.sort(key=lambda p: _ts_key(p), reverse=True)
    return candidates[0]


def write_report_index(target_dir: Path, summary: Dict[str, Any]) -> Path:
    target_dir = Path(target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / "report_index.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def build_report_comparisons(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_job: Dict[str, List[Dict[str, Any]]] = {}
    for item in summaries:
        src = item.get("source") or {}
        job = src.get("job_slug") or "local"
        by_job.setdefault(job, []).append(item)
    comparisons: List[Dict[str, Any]] = []
    for job, rows in by_job.items():
        rows.sort(key=lambda r: (r.get("source", {}).get("timestamp") or ""), reverse=True)
        if len(rows) < 2:
            continue
        latest = rows[0]
        prev = rows[1]
        latest_kpis = latest.get("kpis") or {}
        prev_kpis = prev.get("kpis") or {}
        def _delta(path: List[str]) -> Dict[str, Any]:
            cur = latest_kpis
            old = prev_kpis
            for key in path:
                cur = (cur or {}).get(key)
                old = (old or {}).get(key)
            try:
                return {"current": cur, "previous": old, "delta": (cur - old) if cur is not None and old is not None else None}
            except Exception:
                return {"current": cur, "previous": old, "delta": None}
        comparisons.append(
            {
                "job_slug": job,
                "latest": latest.get("source", {}),
                "previous": prev.get("source", {}),
                "metrics": {
                    "scan_fail": _delta(["scan", "fail"]),
                    "scan_error": _delta(["scan", "error"]),
                    "scan_warn": _delta(["scan", "warn"]),
                    "coverage_line": _delta(["coverage", "line_rate"]),
                    "prqa_rule_violations": _delta(["prqa", "rule_violation_count"]),
                    "vectorcast_avg_pct": _delta(["vectorcast", "metrics_avg_pct"]),
                },
            }
        )
    return comparisons


def _root_from_code_path(path: str) -> Optional[Path]:
    try:
        parts = Path(path).parts
    except Exception:
        return None
    for idx, part in enumerate(parts):
        if str(part).lower() in ("source", "src", "sources"):
            return Path(*parts[: idx + 1])
    if parts:
        return Path(*parts[:-1])
    return None


def _read_text_sample(path: Path, max_bytes: int = 2_000_000) -> str:
    try:
        with path.open("rb") as fh:
            raw = fh.read(max_bytes)
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_roots_from_text(text: str) -> List[Path]:
    if not text:
        return []
    roots: List[Path] = []
    def _clean_candidate(raw: str) -> Optional[str]:
        if not raw:
            return None
        cleaned = str(raw).strip().strip('"').strip("'")
        if ">" in cleaned:
            cleaned = cleaned.split(">", 1)[0].strip()
        if " -" in cleaned:
            cleaned = cleaned.split(" -", 1)[0].strip()
        if not cleaned:
            return None
        if re.search(r"\.exe\b", cleaned, re.IGNORECASE):
            return None
        if not re.match(r"^[A-Za-z]:[\\/]", cleaned):
            return None
        return cleaned

    file_pat = re.compile(r"([A-Za-z]:[\\/][^:\s\"']+?\.(?:c|h|cpp|hpp))", re.IGNORECASE)
    source_pat = re.compile(r"([A-Za-z]:[\\/][^\"'\s]+?[\\/](?:source|src|sources))", re.IGNORECASE)
    workspace_pat = re.compile(
        r"([A-Za-z]:[\\/][^\r\n]+?[\\/]workspace[\\/][^\r\n\s]+)",
        re.IGNORECASE,
    )
    for match in source_pat.findall(text):
        cleaned = _clean_candidate(match)
        if not cleaned:
            continue
        try:
            roots.append(Path(cleaned))
        except Exception:
            continue
    for match in workspace_pat.findall(text):
        cleaned = _clean_candidate(match)
        if not cleaned:
            continue
        try:
            roots.append(Path(cleaned))
            roots.append(Path(cleaned) / "source")
        except Exception:
            continue
    for match in file_pat.findall(text):
        root = _root_from_code_path(match)
        if root:
            roots.append(root)
    return roots


def _collect_text_files(build_root: Path, limit: int = 12) -> List[Path]:
    files: List[Path] = []
    preferred = build_root / "jenkins_console.log"
    if preferred.exists():
        files.append(preferred)
    if len(files) >= limit:
        return files
    patterns = ("*.log", "*.txt", "*.json", "*.html")
    for pattern in patterns:
        for path in build_root.rglob(pattern):
            if path in files:
                continue
            files.append(path)
            if len(files) >= limit:
                return files
    return files


def _count_code_files(root: Path, exts: Iterable[str], limit: int = 5000) -> int:
    count = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if Path(name).suffix.lower() in exts:
                count += 1
                if count >= limit:
                    return count
    return count


def find_jenkins_source_root(build_root: Path, max_depth: int = 5) -> Dict[str, Any]:
    build_root = Path(build_root).resolve()
    if not build_root.exists():
        return {"root": "", "candidates": []}
    exts = {".c", ".h", ".cpp", ".hpp"}
    score_map: Dict[str, int] = {}

    def _add_candidate(path: Path, score: int = 1) -> None:
        try:
            key = str(path)
        except Exception:
            return
        score_map[key] = score_map.get(key, 0) + score

    for root, dirs, _ in os.walk(build_root):
        try:
            depth = len(Path(root).relative_to(build_root).parts)
        except Exception:
            depth = 0
        if depth > max_depth:
            dirs[:] = []
            continue
        base = Path(root).name
        if base.lower() in ("source", "src", "sources"):
            root_path = Path(root)
            count = _count_code_files(root_path, exts)
            _add_candidate(root_path, max(1, count))
            if root_path.exists():
                _add_candidate(root_path, 100)

    for text_path in _collect_text_files(build_root):
        text = _read_text_sample(text_path)
        for root in _extract_roots_from_text(text):
            _add_candidate(root, 2)
            if root.exists():
                _add_candidate(root, 50)

    candidates_all: List[Tuple[int, Path]] = []
    for path_str, score in score_map.items():
        try:
            candidates_all.append((score, Path(path_str)))
        except Exception:
            continue
    candidates_all.sort(key=lambda x: x[0], reverse=True)

    local_candidates = [
        (score, path)
        for score, path in candidates_all
        if path.exists() and path.is_dir()
    ]
    root_path = local_candidates[0][1] if local_candidates else build_root

    if not candidates_all:
        return {
            "root": str(build_root),
            "candidates": [{"path": str(build_root), "score": 0, "exists": True}],
        }
    return {
        "root": str(root_path),
        "candidates": [
            {"path": str(path), "score": score, "exists": path.exists() and path.is_dir()}
            for score, path in candidates_all[:8]
        ],
    }
