# /app/report_generator.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime


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
