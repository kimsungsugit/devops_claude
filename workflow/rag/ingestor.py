# workflow/rag/ingestor.py
# -*- coding: utf-8 -*-
# RAG ingestion functions (extracted from workflow.rag)

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

import config
from workflow.rag.chunker import _chunk_source_file

if TYPE_CHECKING:
    from workflow.rag import KnowledgeBase

_rag_logger = logging.getLogger("workflow.rag")


def _split_paths(val: Any) -> List[str]:
    if not val:
        return []
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    s = str(val or "").strip()
    if not s:
        return []
    parts = [x.strip() for x in s.replace("\n", ",").replace(";", ",").split(",")]
    return [p for p in parts if p]


def _collect_files_from_paths(
    paths: Iterable[str],
    *,
    exts: Optional[Tuple[str, ...]] = None,
    globs: Optional[List[str]] = None,
    max_files: int = 200,
) -> List[Path]:
    files: List[Path] = []
    for p in paths:
        try:
            path = Path(p).expanduser()
        except Exception:
            continue
        if path.is_file():
            files.append(path)
            continue
        if path.is_dir():
            if globs:
                for g in globs:
                    for hit in path.glob(g):
                        if hit.is_file():
                            files.append(hit)
            else:
                for hit in path.rglob("*"):
                    if hit.is_file():
                        files.append(hit)
    if exts:
        files = [f for f in files if f.suffix.lower() in exts]
    # dedup + cap
    uniq: Dict[str, Path] = {}
    for f in files:
        uniq[str(f.resolve())] = f
    return list(uniq.values())[: max(1, int(max_files))]


def _infer_vectorcast_tags(path: Path) -> List[str]:
    name = path.name.lower()
    tags = ["vectorcast"]
    if "ut" in name or "unit" in name:
        tags.append("ut")
    if "it" in name or "integration" in name:
        tags.append("it")
    if "coverage" in name:
        tags.append("coverage")
    return tags


def ingest_external_sources(kb: "KnowledgeBase", cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or {}
    enabled = bool(getattr(config, "RAG_INGEST_ENABLE", True))
    if not enabled:
        return {"enabled": False, "reason": "disabled"}

    max_files = int(cfg.get("rag_ingest_max_files") or getattr(config, "RAG_INGEST_MAX_FILES", 200))
    max_chunks = int(
        cfg.get("rag_ingest_max_chunks") or getattr(config, "RAG_INGEST_MAX_CHUNKS_PER_FILE", 12)
    )
    chunk_size = int(cfg.get("rag_chunk_size") or getattr(config, "RAG_CHUNK_SIZE", 1200))
    overlap = int(cfg.get("rag_chunk_overlap") or getattr(config, "RAG_CHUNK_OVERLAP", 200))

    vc_paths = _split_paths(cfg.get("vc_reports_paths") or getattr(config, "VC_REPORTS_PATHS", ""))
    uds_paths = _split_paths(cfg.get("uds_spec_paths") or getattr(config, "UDS_SPEC_PATHS", ""))
    req_paths = _split_paths(cfg.get("req_docs_paths") or getattr(config, "REQ_DOCS_PATHS", ""))
    code_paths = _split_paths(cfg.get("codebase_paths") or getattr(config, "CODEBASE_PATHS", ""))

    idx = kb._load_external_index()
    updated = 0
    skipped = 0

    def _ingest(
        paths: List[str],
        *,
        category: str,
        tags: Any,
        exts: Tuple[str, ...],
        globs: Optional[List[str]] = None,
    ):
        nonlocal updated, skipped, idx
        files = _collect_files_from_paths(paths, exts=exts, globs=globs, max_files=max_files)
        for fp in files:
            try:
                _st = fp.stat()
                sig = f"{_st.st_mtime_ns}:{_st.st_size}"
            except Exception:
                sig = ""
            key = f"{category}:{fp.as_posix()}"
            if sig and idx.get(key) == sig:
                skipped += 1
                continue

            chunks = _chunk_source_file(
                fp,
                chunk_size=chunk_size,
                overlap=overlap,
                max_chunks=max_chunks,
            )
            if not chunks:
                skipped += 1
                continue
            use_tags: List[str] = []
            try:
                if callable(tags):
                    use_tags = list(tags(fp))
                elif isinstance(tags, list):
                    use_tags = list(tags)
            except Exception:
                use_tags = []

            for i, ch in enumerate(chunks):
                title = f"{category}:{fp.name}#{i+1}"
                kb.add_document(
                    title=title,
                    content=ch,
                    category=category,
                    tags=use_tags,
                    source_file=str(fp),
                )
                updated += 1
            if sig:
                idx[key] = sig

    if vc_paths:
        _ingest(
            vc_paths,
            category="vectorcast",
            tags=_infer_vectorcast_tags,
            exts=(".html", ".htm", ".csv", ".txt", ".log"),
        )
    if uds_paths:
        _ingest(
            uds_paths,
            category="uds",
            tags=["uds"],
            exts=(".pdf", ".docx", ".txt", ".md", ".xlsx"),
        )
    if req_paths:
        _ingest(
            req_paths,
            category="requirements",
            tags=["requirements"],
            exts=(".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx"),
        )
    if code_paths:
        _ingest(
            code_paths,
            category="code",
            tags=["code"],
            exts=(".c", ".h", ".cpp", ".hpp"),
            globs=list(getattr(config, "CODE_RAG_GLOBS", [])) or None,
        )

    if updated or skipped:
        kb._save_external_index(idx)
    return {"enabled": True, "updated": updated, "skipped": skipped}


def ingest_uds_reference(
    kb: "KnowledgeBase",
    *,
    ref_suds_path: Optional[str] = None,
    function_details: Optional[Dict[str, Any]] = None,
    globals_info_map: Optional[Dict[str, Any]] = None,
    req_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """Ingest UDS-specific data into RAG KB with specialized categories."""
    counts = {"uds_description": 0, "uds_globals": 0, "uds_requirements": 0, "uds_reference": 0}

    if ref_suds_path:
        rpath = Path(ref_suds_path)
        if rpath.exists() and rpath.suffix.lower() == ".docx":
            chunks = _chunk_source_file(rpath, chunk_size=1500, overlap=300, max_chunks=50)
            for i, ch in enumerate(chunks):
                kb.add_document(
                    title=f"uds_reference:{rpath.name}#{i+1}",
                    content=ch,
                    category="uds_description",
                    tags=["uds_description", "reference"],
                    source_file=str(rpath),
                )
                counts["uds_reference"] += 1

    if isinstance(function_details, dict):
        batch_lines: List[str] = []
        for fid, info in function_details.items():
            if not isinstance(info, dict):
                continue
            desc = str(info.get("description") or "").strip()
            dsrc = str(info.get("description_source") or "").strip()
            if dsrc in {"comment", "sds", "reference"} and desc and len(desc) > 10:
                fname = str(info.get("name") or "").strip()
                proto = str(info.get("prototype") or "").strip()[:100]
                batch_lines.append(f"{fname}: {desc} [{proto}]")
                if len(batch_lines) >= 20:
                    kb.add_document(
                        title=f"uds_description:batch_{counts['uds_description']}",
                        content="\n".join(batch_lines),
                        category="uds_description",
                        tags=["uds_description"],
                    )
                    counts["uds_description"] += 1
                    batch_lines = []
        if batch_lines:
            kb.add_document(
                title=f"uds_description:batch_{counts['uds_description']}",
                content="\n".join(batch_lines),
                category="uds_description",
                tags=["uds_description"],
            )
            counts["uds_description"] += 1

    if isinstance(globals_info_map, dict) and globals_info_map:
        globals_lines: List[str] = []
        for gname, ginfo in globals_info_map.items():
            if not isinstance(ginfo, dict):
                continue
            gtype = str(ginfo.get("type") or "").strip()
            gfile = Path(str(ginfo.get("file") or "")).name
            gdesc = str(ginfo.get("desc") or "").strip()
            globals_lines.append(f"{gname} ({gtype}) [{gfile}] {gdesc}".strip())
            if len(globals_lines) >= 30:
                kb.add_document(
                    title=f"uds_globals:batch_{counts['uds_globals']}",
                    content="\n".join(globals_lines),
                    category="uds_globals",
                    tags=["uds_globals", "globals"],
                )
                counts["uds_globals"] += 1
                globals_lines = []
        if globals_lines:
            kb.add_document(
                title=f"uds_globals:batch_{counts['uds_globals']}",
                content="\n".join(globals_lines),
                category="uds_globals",
                tags=["uds_globals", "globals"],
            )
            counts["uds_globals"] += 1

    if isinstance(req_map, dict) and req_map:
        req_lines: List[str] = []
        for rid, rinfo in req_map.items():
            if isinstance(rinfo, dict):
                rdesc = str(rinfo.get("description") or rinfo.get("text") or "").strip()
                req_lines.append(f"{rid}: {rdesc[:200]}")
            elif isinstance(rinfo, str):
                req_lines.append(f"{rid}: {rinfo[:200]}")
            if len(req_lines) >= 25:
                kb.add_document(
                    title=f"uds_requirements:batch_{counts['uds_requirements']}",
                    content="\n".join(req_lines),
                    category="uds_requirements",
                    tags=["uds_requirements", "requirements"],
                )
                counts["uds_requirements"] += 1
                req_lines = []
        if req_lines:
            kb.add_document(
                title=f"uds_requirements:batch_{counts['uds_requirements']}",
                content="\n".join(req_lines),
                category="uds_requirements",
                tags=["uds_requirements", "requirements"],
            )
            counts["uds_requirements"] += 1

    _rag_logger.info("UDS reference ingestion: %s", counts)
    return counts


def ingest_runtime_summary(kb: "KnowledgeBase", summary: Dict[str, Any], report_dir: Path) -> Dict[str, Any]:
    if not bool(getattr(config, "RAG_INGEST_RUNTIME_ENABLE", True)):
        return {"enabled": False, "reason": "disabled"}
    updated = 0

    def _add_runtime(category: str, title: str, content: str, source_file: str) -> None:
        nonlocal updated
        kb.add_document(
            title=title,
            content=content[: int(getattr(config, "RAG_CONTEXT_MAX_CHARS", 4000))],
            category=category,
            tags=[category, "runtime"],
            source_file=source_file,
        )
        updated += 1

    build = summary.get("build", {}) if isinstance(summary.get("build"), dict) else {}
    coverage = summary.get("coverage", {}) if isinstance(summary.get("coverage"), dict) else {}
    tests = summary.get("tests", {}) if isinstance(summary.get("tests"), dict) else {}

    build_ctx = json.dumps(
        {
            "reason": build.get("reason"),
            "data": build.get("data", {}),
        },
        ensure_ascii=False,
    )
    _add_runtime("build", "runtime:build", build_ctx, "runtime:build")

    tests_ctx = json.dumps(
        {
            "enabled": tests.get("enabled"),
            "mode": tests.get("mode"),
            "results": tests.get("results", [])[:50],
            "execution": tests.get("execution", {}),
        },
        ensure_ascii=False,
    )
    _add_runtime("tests", "runtime:tests", tests_ctx, "runtime:tests")

    cov_ctx = json.dumps(
        {
            "enabled": coverage.get("enabled"),
            "ok": coverage.get("ok"),
            "line_rate": coverage.get("line_rate"),
            "line_rate_pct": coverage.get("line_rate_pct"),
            "branch_rate": coverage.get("branch_rate"),
            "branch_rate_pct": coverage.get("branch_rate_pct"),
            "threshold": coverage.get("threshold"),
            "reason": coverage.get("reason") or coverage.get("parse_error"),
        },
        ensure_ascii=False,
    )
    _add_runtime("coverage", "runtime:coverage", cov_ctx, "runtime:coverage")

    return {"ok": True, "updated": updated, "report_dir": str(report_dir)}
