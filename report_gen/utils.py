"""report_gen.utils - Auto-split from report_generator.py"""
# Re-import common dependencies
import re
import os
import json
import csv
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from datetime import datetime

from report_gen.source_parser import _read_text_limited  # noqa: F401  (leaf module, no circular dep)

_logger = logging.getLogger("report_generator")

def _safe_dict(x) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _safe_list(x) -> List[Any]:
    return x if isinstance(x, list) else []


def _fmt_bool(x: Any) -> str:
    if x is True:
        return "YES"
    if x is False:
        return "NO"
    return "N/A"


def _extract_issue_counts(summary: Dict[str, Any]) -> Dict[str, int]:
    static_block = _safe_dict(summary.get("static", {}))
    cpp = _safe_dict(static_block.get("cppcheck", {}))
    counts = _safe_dict(cpp.get("issue_counts", {}))
    if counts:
        return {
            "total": int(counts.get("total", 0) or 0),
            "error": int(counts.get("error", 0) or 0),
            "warning": int(counts.get("warning", 0) or 0),
        }
    data = _safe_dict(cpp.get("data", {}))
    issues = _safe_list(data.get("issues", []))
    return {"total": len(issues), "error": 0, "warning": 0}


def generate_markdown_summary(summary: Dict[str, Any], output_path: str) -> str:
    """analysis_summary.json 기반의 간단한 Markdown 요약 리포트 생성."""
    summary = _safe_dict(summary)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    project_root = str(summary.get("project_root") or "")
    project_name = Path(project_root).name if project_root else "Project Analysis Report"
    generated_at = summary.get("generated_at") or datetime.now().isoformat(timespec="seconds")

    static_counts = _extract_issue_counts(summary)
    cov = _safe_dict(summary.get("coverage", {}))
    tests = _safe_dict(summary.get("tests", {}))
    build = _safe_dict(summary.get("build", {}))
    fuzz = _safe_dict(summary.get("fuzzing", {}))
    qemu = _safe_dict(summary.get("qemu", {}))
    domain = _safe_dict(summary.get("domain_tests", {}))
    docs = _safe_dict(summary.get("docs", {}))
    report_health = _safe_dict(summary.get("report_health", {}))
    scm = _safe_dict(summary.get("scm", {}))
    git = _safe_dict(summary.get("git", {}))
    svn = _safe_dict(summary.get("svn", {}))
    strict = _safe_dict(summary.get("strict", {}))
    artifacts = _safe_dict(summary.get("artifacts", {}))

    line_rate = cov.get("line_rate")
    if line_rate is not None:
        line_rate = f"{float(line_rate) * 100:.1f}%"
    else:
        line_rate = "N/A"

    missing = ", ".join(report_health.get("missing") or []) or "none"
    warnings = ", ".join(report_health.get("warnings") or []) or "none"

    lines: List[str] = []
    lines.append(f"# {project_name}")
    lines.append("")
    lines.append(f"- Generated at: {generated_at}")
    lines.append(f"- Exit code: {summary.get('exit_code', 0)}")
    lines.append(f"- Failure stage: {summary.get('failure_stage', 'none')}")
    lines.append(f"- Change mode: {summary.get('change_mode', 'full')}")
    lines.append("")

    lines.append("## SCM")
    lines.append(f"- Mode: {scm.get('mode')}")
    lines.append(f"- Git status: {git.get('status')} | branch: {git.get('branch')} | commit: {git.get('commit')} | dirty: {git.get('dirty')}")
    lines.append(f"- SVN status: {svn.get('status')} | revision: {svn.get('revision')} | dirty: {svn.get('dirty')}")
    lines.append("")

    lines.append("## Results")
    lines.append(f"- Build: enabled={_fmt_bool(build.get('enabled'))}, ok={_fmt_bool(build.get('ok'))}, reason={build.get('reason')}")
    lines.append(f"- Tests: enabled={_fmt_bool(tests.get('enabled'))}, ok={_fmt_bool(tests.get('ok'))}, reason={tests.get('reason')}")
    lines.append(f"- Static issues: total={static_counts.get('total', 0)}, error={static_counts.get('error', 0)}, warning={static_counts.get('warning', 0)}")
    lines.append(f"- Coverage: enabled={_fmt_bool(cov.get('enabled'))}, line={line_rate}, threshold={cov.get('threshold')}, below={_fmt_bool(cov.get('below_threshold'))}")
    lines.append(f"- Fuzzing: enabled={_fmt_bool(fuzz.get('enabled'))}, ok={_fmt_bool(fuzz.get('ok'))}, reason={fuzz.get('reason')}")
    lines.append(f"- QEMU: enabled={_fmt_bool(qemu.get('enabled'))}, ok={_fmt_bool(qemu.get('ok'))}, reason={qemu.get('reason')}")
    lines.append(f"- Domain tests: enabled={_fmt_bool(domain.get('enabled'))}, ok={_fmt_bool(domain.get('ok'))}, reason={domain.get('reason')}")
    lines.append(f"- Docs: enabled={_fmt_bool(docs.get('enabled'))}, ok={_fmt_bool(docs.get('ok'))}, reason={docs.get('reason')}")
    lines.append("")

    lines.append("## Report Health")
    lines.append(f"- Missing: {missing}")
    lines.append(f"- Warnings: {warnings}")
    lines.append("")

    lines.append("## Strict Mode")
    lines.append(f"- CI env: {_fmt_bool(strict.get('ci_env'))}")
    lines.append(f"- Fuzz strict: {_fmt_bool(strict.get('fuzz_strict'))}")
    lines.append(f"- QEMU strict: {_fmt_bool(strict.get('qemu_strict'))}")
    lines.append(f"- Domain strict: {_fmt_bool(strict.get('domain_tests_strict'))}")
    lines.append("")

    lines.append("## Artifacts")
    if artifacts:
        lines.append(f"- Summary JSON: {artifacts.get('summary_json')}")
        lines.append(f"- Summary MD: {artifacts.get('summary_md')}")
        lines.append(f"- Findings JSON: {artifacts.get('findings_flat')}")
        lines.append(f"- Pipeline log: {artifacts.get('pipeline_log')}")
    else:
        lines.append("- No artifact metadata recorded")
    lines.append("")

    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(out)


def generate_pdf_report(summary: Dict[str, Any], output_path: str) -> str:
    """
    GUI에서 호출하는 PDF 리포트 생성 함수
    - summary 기반 섹션을 확장
    - ASan/Fuzz/QEMU/Domain/Coverage/Complexity 템플릿 포함
    """
    summary = _safe_dict(summary)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
    except Exception as e:
        raise ImportError(
            "reportlab 미설치로 PDF 생성 불가. requirements에 reportlab 추가 필요"
        ) from e

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(out), pagesize=A4)
    story: List[Any] = []

    def H(text: str):
        story.append(Paragraph(text, styles["Heading2"]))
        story.append(Spacer(1, 8))

    def P(text: str):
        story.append(Paragraph(text, styles["BodyText"]))
        story.append(Spacer(1, 6))

    def KV(rows: List[Tuple[str, str]]):
        t = Table([["Key", "Value"]] + [[k, v] for k, v in rows], colWidths=[160, 360])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))

    # ------------------------------------------------------------
    # 1) Header
    # ------------------------------------------------------------
    title = summary.get("project") or summary.get("project_name") or "Project Analysis Report"
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 6))
    P(f"Generated at: {summary.get('generated_at') or datetime.now().isoformat(timespec='seconds')}")

    # ------------------------------------------------------------
    # 2) Overall Summary
    # ------------------------------------------------------------
    H("Overall Summary")
    KV([
        ("Exit Code", str(summary.get("exit_code", 0))),
        ("Failure Stage", str(summary.get("failure_stage", "none"))),
        ("Change Mode", str(summary.get("change_mode", "full"))),
    ])

    # ------------------------------------------------------------
    # 3) Static Analysis
    # ------------------------------------------------------------
    H("Static Analysis (Cppcheck / Clang-Tidy)")
    issue_counts = _extract_issue_counts(summary)
    static_block = _safe_dict(summary.get("static", {}))
    cpp = _safe_dict(static_block.get("cppcheck", {}))
    tidy = _safe_dict(static_block.get("clang_tidy", {}))

    KV([
        ("Cppcheck Enabled", _fmt_bool(cpp.get("enabled"))),
        ("Cppcheck OK", _fmt_bool(cpp.get("ok"))),
        ("Cppcheck Issues", str(issue_counts.get("total", 0))),
        ("Clang-Tidy Enabled", _fmt_bool(tidy.get("enabled"))),
        ("Clang-Tidy OK", _fmt_bool(tidy.get("ok"))),
    ])

    # ------------------------------------------------------------
    # 4) Build & Tests (+ ASan template)
    # ------------------------------------------------------------
    H("Build & Tests")
    build = _safe_dict(summary.get("build", {}))
    bdata = _safe_dict(build.get("data", {}))

    asan_enabled = bdata.get("asan_enabled")
    if asan_enabled is None:
        asan_enabled = bool(bdata.get("asan")) or bool(bdata.get("address_sanitizer"))

    KV([
        ("Build Enabled", _fmt_bool(build.get("enabled"))),
        ("Build OK", _fmt_bool(build.get("ok"))),
        ("Reason", str(build.get("reason", ""))),
        ("ASan Enabled (heuristic)", _fmt_bool(asan_enabled)),
    ])

    tests = _safe_dict(summary.get("tests", {}))
    KV([
        ("Unit Tests Enabled", _fmt_bool(tests.get("enabled"))),
        ("Unit Tests OK", _fmt_bool(tests.get("ok"))),
        ("Reason", str(tests.get("reason", ""))),
    ])

    # ------------------------------------------------------------
    # 5) Coverage
    # ------------------------------------------------------------
    H("Coverage")
    cov = _safe_dict(summary.get("coverage", {}))
    line_rate = cov.get("line_rate")
    line_pct = f"{float(line_rate)*100:.1f}%" if line_rate is not None else "N/A"

    KV([
        ("Coverage Enabled", _fmt_bool(cov.get("enabled"))),
        ("Line Coverage", line_pct),
        ("Threshold", str(cov.get("threshold", ""))),
        ("Below Threshold", _fmt_bool(cov.get("below_threshold"))),
        ("HTML", str(cov.get("html", ""))),
    ])

    # ------------------------------------------------------------
    # 6) Fuzzing
    # ------------------------------------------------------------
    H("AI / LibFuzzer Fuzzing")
    fuzz = _safe_dict(summary.get("fuzzing", {}))
    fdata = _safe_dict(fuzz.get("data", {}))
    results = _safe_list(fuzz.get("results")) or _safe_list(fdata.get("results"))
    targets = _safe_list(fuzz.get("targets")) or _safe_list(fdata.get("targets"))

    crash_found = fuzz.get("crash_found")
    if crash_found is None:
        crash_found = any(isinstance(r, dict) and (r.get("crash") or r.get("crash_found")) for r in results)

    KV([
        ("Fuzz Enabled", _fmt_bool(fuzz.get("enabled"))),
        ("Targets", str(len(targets) or len(results))),
        ("Crash Found", _fmt_bool(crash_found)),
        ("Reason", str(fuzz.get("reason", ""))),
    ])

    # ------------------------------------------------------------
    # 7) QEMU
    # ------------------------------------------------------------
    H("QEMU Smoke Test")
    qemu = _safe_dict(summary.get("qemu", {}))
    KV([
        ("QEMU Enabled", _fmt_bool(qemu.get("enabled"))),
        ("QEMU OK", _fmt_bool(qemu.get("ok"))),
        ("Reason", str(qemu.get("reason", ""))),
    ])

    # ------------------------------------------------------------
    # 8) Domain Tests
    # ------------------------------------------------------------
    H("Domain Target Tests")
    dom = _safe_dict(summary.get("domain_tests", {}))
    KV([
        ("Domain Tests Enabled", _fmt_bool(dom.get("enabled"))),
        ("Domain Tests OK", _fmt_bool(dom.get("ok"))),
        ("Total", str(dom.get("total", ""))),
        ("Failed", str(dom.get("failed", ""))),
        ("Reason", str(dom.get("reason", ""))),
    ])

    # ------------------------------------------------------------
    # 9) Complexity (template)
    # ------------------------------------------------------------
    H("Complexity (Lizard)")
    comp = _safe_dict(summary.get("complexity", {}))
    # summary에 직접 없을 수 있어 템플릿 형태로 제공
    KV([
        ("Complexity Embedded in Summary", _fmt_bool(bool(comp))),
        ("Avg CCN", str(comp.get("avg_ccn", ""))),
        ("Max CCN", str(comp.get("max_ccn", ""))),
        ("Functions", str(comp.get("functions", ""))),
        ("Note", "상세 데이터는 GUI 복잡도 탭의 CSV 기반 확인 권장"),
    ])

    doc.build(story)
    return str(out)


def _extract_simple_call_names(body_text: str) -> List[str]:
    if not body_text:
        return []
    from report_gen.function_analyzer import _strip_comments_and_strings  # lazy: circular dep
    text = _strip_comments_and_strings(body_text)
    skip = {
        "if",
        "for",
        "while",
        "switch",
        "return",
        "sizeof",
        "case",
        "else",
    }
    names: List[str] = []
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", text):
        name = str(m.group(1) or "").strip()
        if not name or name.lower() in skip:
            continue
        # Avoid counting macro-like invocations as function calls.
        if name.isupper():
            continue
        if name not in names:
            names.append(name)
    # function-pointer style call: (*fn)(...)
    for m in re.finditer(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)\s*\(", text):
        name = str(m.group(1) or "").strip()
        if not name or name.lower() in skip:
            continue
        if name not in names:
            names.append(name)
    return names


def _table_rows_from_texts(rows: List[str], cols: int) -> List[List[str]]:
    from report_gen.requirements import _normalize_table_row  # lazy: circular dep
    out: List[List[str]] = []
    for row in rows:
        parts = _normalize_table_row(row)
        if not parts:
            continue
        while len(parts) < cols:
            parts.append("")
        out.append(parts[:cols])
    return out


def _build_global_rows(
    names: List[str],
    globals_info: Dict[str, Dict[str, str]],
    header_row: List[str],
    with_labels: bool = True,
) -> List[List[str]]:
    if not names:
        return []
    cols = len(header_row)
    rows: List[List[str]] = []
    for name in names:
        info = globals_info.get(name, {})
        gtype = info.get("type") or ""
        grange = info.get("range") or ""
        ginit = info.get("init") or ""
        gdesc = info.get("desc") or ""
        row = [""] * cols
        for idx, col in enumerate(header_row):
            col_norm = (col or "").strip().lower()
            if "name" in col_norm:
                row[idx] = f"Name={name}" if with_labels else name
            elif "type" in col_norm:
                row[idx] = f"Type={gtype}" if with_labels else gtype
            elif "value range" in col_norm or "range" in col_norm:
                row[idx] = f"Range={grange}" if with_labels else grange
            elif "reset" in col_norm:
                row[idx] = f"Reset={ginit}" if with_labels else ginit
            elif "description" in col_norm:
                row[idx] = f"Description={gdesc}" if with_labels else gdesc
        rows.append(row)
    return rows


def _normalize_swufn_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    m = re.search(r"swufn_(\d+)", text, flags=re.I)
    if m:
        return f"SwUFn_{m.group(1)}"
    return text


def _normalize_call_field(value: str) -> str:
    lines: List[str] = []
    for raw in str(value or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line not in lines:
            lines.append(line)
    return "\n".join(lines)


def _dedupe_multiline_text(value: str, na_to_empty: bool = False) -> str:
    out: List[str] = []
    for raw in str(value or "").splitlines():
        line = str(raw or "").strip()
        if not line:
            continue
        if na_to_empty and line.upper() in {"N/A", "NONE", "-", "TBD"}:
            continue
        if line not in out:
            out.append(line)
    return "\n".join(out).strip()


def _normalize_asil_value(value: str) -> str:
    tokens: List[str] = []
    for raw in re.split(r"[\s,;/]+", str(value or "").strip()):
        t = str(raw or "").strip().upper()
        if not t:
            continue
        if t in {"A", "B", "C", "D", "QM", "ASIL-A", "ASIL-B", "ASIL-C", "ASIL-D"}:
            canon = t.replace("ASIL-", "")
            if canon not in tokens:
                tokens.append(canon)
    if not tokens:
        text = _dedupe_multiline_text(str(value or ""), na_to_empty=True)
        return text
    return ", ".join(tokens)


def _normalize_related_ids(value: str) -> str:
    tokens: List[str] = []
    for raw in re.split(r"[,;\n]+", str(value or "")):
        t = str(raw or "").strip()
        if not t:
            continue
        if t not in tokens:
            tokens.append(t)
    return ", ".join(tokens)


def _extract_call_names(value: str) -> List[str]:
    skip_tokens = {
        "void",
        "u8",
        "u16",
        "u32",
        "s8",
        "s16",
        "s32",
        "bool",
        "float",
        "double",
        "char",
        "int",
        "long",
        "short",
        "const",
        "static",
        "extern",
        "volatile",
        "return",
        "if",
        "else",
        "while",
        "for",
        "switch",
        "case",
        "default",
        "do",
        "sizeof",
    }
    names: List[str] = []
    for raw in str(value or "").splitlines():
        line = raw.strip().rstrip(";")
        if not line:
            continue
        m = re.search(r"\b([A-Za-z_]\w*)\s*\(", line)
        if m:
            cand = m.group(1).strip()
            if str(cand).lower() == "isr":
                m_isr = re.search(r"\bISR\s*\(\s*([A-Za-z_]\w*)\s*\)", line, flags=re.I)
                if m_isr:
                    cand = m_isr.group(1).strip()
        else:
            # Handle styles like "ISR (Some_Handler)" in reference-like documents.
            m_isr = re.search(r"\bISR\s*\(\s*([A-Za-z_]\w*)\s*\)", line, flags=re.I)
            if m_isr:
                cand = m_isr.group(1).strip()
            else:
                cand = line
        cand = str(cand or "").strip()
        if not cand:
            continue
        if re.search(r"[\s,\[\]\{\}\*]", cand):
            continue
        if not re.match(r"^[A-Za-z_]\w*$", cand):
            continue
        if cand.lower() in skip_tokens:
            continue
        if cand and cand not in names:
            names.append(cand)
    return names


def _normalize_swcom_label(label: str) -> str:
    text = " ".join(str(label or "").split()).strip()
    if not text:
        return ""
    m = re.search(r"\bSw\s*Com\s*[_-]?\s*(\d{1,2})\b", text, flags=re.I)
    if m:
        num = m.group(1).zfill(2)
        text = re.sub(r"\bSw\s*Com\s*[_-]?\s*\d{1,2}\b", f"SwCom_{num}", text, flags=re.I)
    text = re.sub(r"\s*\(\s*", "(", text)
    text = re.sub(r"\s*\)\s*", ")", text)
    return text


def _infer_type_from_decl(decl: str, name: str) -> str:
    if not decl or not name:
        return ""
    text = " ".join(decl.replace("\n", " ").split())
    m = re.search(rf"(.+?)\\b{name}\\b", text)
    if not m:
        return ""
    head = m.group(1)
    head = re.sub(r"\\s*=", " ", head).strip()
    head = re.sub(r"\\b(static|extern|const|volatile)\\b", "", head).strip()
    return " ".join(head.split()).strip()


def _infer_type_from_file(file_path: str, name: str) -> Tuple[str, str]:
    if not file_path or not name:
        return "", ""
    try:
        text = _read_text_limited(Path(file_path), 200_000)
    except Exception:
        return "", ""
    name_re = re.escape(name)
    try:
        pattern = re.compile(rf"^\\s*(.+?)\\b{name_re}\\b\\s*(=|\\[|;)", re.M)
    except re.error:
        return "", ""
    for match in pattern.finditer(text):
        decl = match.group(0)
        if "(" in decl:
            continue
        head = match.group(1)
        head = re.sub(r"\\b(static|extern|const|volatile)\\b", "", head).strip()
        gtype = " ".join(head.split()).strip()
        init = ""
        init_match = re.search(rf"\\b{name}\\b\\s*=\\s*([^;]+)", decl)
        if init_match:
            init = init_match.group(1).strip()
        if gtype:
            return gtype, init
    return "", ""


