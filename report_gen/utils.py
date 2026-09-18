"""report_gen.utils - Auto-split from report_generator.py"""
# Re-import common dependencies
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from report_gen.source_parser import _cap_and_decode, _read_bytes_resolver_aware  # leaf module, no circular dep
from workflow.code_parser.c_parser import (  # noqa: F401 — normalize_prototype_text 재수출(단일 출처는 파서 쪽, R56)
    blank_dead_code,
    normalize_prototype_text,
)

_logger = logging.getLogger("report_generator")

def function_name_key(name: Any) -> str:
    """`function_details_by_name` 의 **키 규칙 단일 출처**.

    ⚠ 이 규칙이 갈리면 조용히 깨진다. 2026-08-03 실측:

        report_gen/uds_generator.py::_put_by_name   `.strip().lower()`   ← 정본
        backend/routers/jenkins.py                  `.strip().lower()`   ✓
        backend/routers/local.py                    `.strip()`           ✗ 원형 유지
        tools/generate_uds_local.py                 `.strip()`           ✗ 원형 유지

    그런데 **조회는 전부 소문자**다 — `docx_builder` 13곳, `backend/routers/code.py:126`,
    `backend/routers/test_gen.py:32`, `uds_generator` 4곳. 즉 local 경로에서 만든 맵은
    이름에 대문자가 있는 함수를 **전부 못 찾는다**. 실측 표본에서 350개 중 **267개(76.3%)**
    가 대문자를 포함한다.

    맞으면 아무 일도 안 일어나고 틀리면 조용히 miss 다 — 그래서 규칙을 한 곳에 둔다.
    """
    return str(name or "").strip().lower()


def build_function_details_by_name(details: Any) -> Dict[str, Any]:
    """`function_details` → `function_details_by_name`(이름 키) 재구성.

    라우터 3곳(local·jenkins·tools)이 같은 루프를 복제하고 있었고 그중 둘이 키 규칙을
    틀렸다. 값은 **원본 객체 그대로** 담는다 — 사본을 넣으면 문서 생성의 in-place 갱신이
    반영되지 않는다(`uds_generator._put_by_name` docstring 참조).

    동명 함수는 last-wins 다(기존 동작 유지). 충돌 기록이 필요한 경로는
    `_put_by_name(collisions=...)` 를 쓴다.
    """
    out: Dict[str, Any] = {}
    if not isinstance(details, dict):
        return out
    for info in details.values():
        if not isinstance(info, dict):
            continue
        key = function_name_key(info.get("name"))
        if key:
            out[key] = info
    return out


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
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
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
    raw_str = str(value or "").strip()
    # N/A·미적용·TBD류는 'ASIL 미부여'(빈 문자열)로 정규화한다. split이 'N/A'를 ['N','A']로
    # 쪼개 'A'로 거짓 격상하던 안전 결함 차단(ISO 26262 ASIL 도출 정확성 — 추적성 갭 판정에
    # 직접 영향). 'NA'(슬래시 없음)도 동일 처리.
    if re.fullmatch(r"\s*(?:n\s*/?\s*a|tbd|none|미적용|해당\s*없음)\s*", raw_str, re.IGNORECASE):
        return ""
    tokens: List[str] = []
    # 괄호도 구분자로 포함 — 'B(C)'(공백 없는 보조등급 표기)를 ['B','C']로 분해해 등급
    # 탈락(미상 처리)을 방지. 'D (B)' 등 기존 케이스는 영향 없음.
    for raw in re.split(r"[\s,;/()]+", raw_str):
        t = str(raw or "").strip().upper()
        if not t:
            continue
        if t in {"A", "B", "C", "D", "QM", "ASIL-A", "ASIL-B", "ASIL-C", "ASIL-D"}:
            canon = t.replace("ASIL-", "")
            if canon not in tokens:
                tokens.append(canon)
    if not tokens:
        text = _dedupe_multiline_text(raw_str, na_to_empty=True)
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
    text = str(value or "")
    # (R56 N52) 여러 줄 프로토타입 — 소스가 `(` 를 다음 줄에 두면(LIN 드라이버 스타일, KJPDS02 50건) 이름 줄에 `(` 가
    #   없어 줄 단위 검사가 이름을 잃었다(run 2086 accuracy 잔여 3건 전부 이 경우). 주석을 지우고 `이름⏎(` 를 한 줄로
    #   붙인 뒤 줄을 본다. 구판 산출물·정본의 프로토타입 칸을 읽을 때를 위한 방어 — 새 산출물은 이름만 싣는다.
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    #   (리뷰 I1) 개행은 **한 번만** 넘는다 — `\s*` 면 빈 줄 건너 다음 항목의 `(` 까지 붙여 뒤 이름을 지울 수 있다.
    text = re.sub(r"([A-Za-z_]\w*)[ \t]*\r?\n[ \t]*\(", r"\1(", text)
    for raw in text.splitlines():
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


# 저장소가 오래 지고 있던 **죽은 폴백** 두 개(2026-08-12 발견).
#
# 아래 두 함수의 정규식이 raw 문자열 안에서 `\\b` · `\\s` 였다. raw 에서 `\\` 는
# **리터럴 백슬래시**이므로 `\\b` 는 "역슬래시 다음에 b" 를 요구한다 — C 소스엔 그런
# 문자열이 없으니 **한 번도 매치된 적이 없다**:
#
#     _infer_type_from_decl("extern volatile ADC0STSSTR _ADC0STS;", "_ADC0STS")  ->  ""
#
# 파일 자동 분할(`Auto-split from report_generator.py`) 때 한 단계 더 이스케이프된
# 것으로 보이며, 둘 다 조용히 `""` 를 돌려주므로 "타입을 못 구했다" 와 구분되지 않았다.
#
# ⚠ 이 fix 는 KJPDS02 에서 **산출물을 바꾸지 않는다** — tree-sitter 가 이미 모든 전역에
#   타입을 주고 있어 `typeless_dropped` 가 0 이다(실측). 즉 회수가 아니라 **폴백의
#   복구**다. tree-sitter 가 실패하는 프로젝트에서만 효과가 있다. 없는 회수를
#   있다고 적지 않기 위해 여기 명시한다.
# 타입 자리로 인정할 모양: (struct|union|enum) 태그? + 식별자 1개 이상 + 포인터
_RE_TYPE_HEAD = re.compile(r"^(?:(?:struct|union|enum)\s+)?[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s*\**$")


def _is_type_head(text: str) -> bool:
    """'선언의 타입 자리' 로 인정할 수 있는 모양인가.

    ⚠ 아래 두 폴백은 정규식으로 이름 앞부분을 잘라 타입이라 부르는데, **'선언' 이라는
    개념이 없다.** 그래서 선언이 아닌 줄에서도 타입을 만들어 낸다:

        `}   s_BuzzerState;`          ->  '}'                (익명 enum 의 닫는 줄)
        `s_BuzzerState = en_s_Stop;`  ->  's_BuzzerState ='   (그냥 대입문)

    이렇게 만든 값이 그대로 ISO 26262 설계서 Type 칸에 실렸다 — 실측 산출물 2,406칸 중
    24칸이 `enum }` 또는 열거자 본문이었고, 정본 2,751칸 중 중괄호 포함은 **0개**다.
    모양이 아니면 `""` 를 돌려 "타입을 못 구했다" 로 남긴다(지어내지 않는다).
    """
    return bool(_RE_TYPE_HEAD.match((text or "").strip()))


def _infer_type_from_decl(decl: str, name: str) -> str:
    if not decl or not name:
        return ""
    text = " ".join(decl.replace("\n", " ").split())
    m = re.search(rf"(.+?)\b{re.escape(name)}\b", text)
    if not m:
        return ""
    head = m.group(1)
    head = re.sub(r"\s*=", " ", head).strip()
    head = re.sub(r"\b(static|extern|const|volatile)\b", "", head).strip()
    head = " ".join(head.split()).strip()
    return head if _is_type_head(head) else ""


def _iter_decl_matches(text: str, name: str, pattern: "re.Pattern[str]") -> Iterator["re.Match[str]"]:
    """`pattern`(= `^\\s*(.+?)\\b{name}\\b\\s*(=|\\[|;)`, re.M) 의 `finditer(text)` 와 **같은 매치를 같은 순서로**
    내되, 이름이 실제로 나오는 줄의 머리에서만 정규식을 돌린다.

    왜: 원판은 줄마다 `^\\s*(.+?)` 를 게으르게 늘리며 이름을 찾아 파일 전체를 훑는다 — 이름이 파일에 **없을 때가 가장
    느리다**. 실측(R52 N41, kjpds02_pv): 폴백 25,007회 중 22,627회(90%)가 그 파일에 이름이 아예 없는 호출이었다
    (tree-sitter 가 '그 파일이 쓰는 전역' 을 파일에 귀속시키므로 선언은 다른 파일에 있다).

    등가 근거: 매치는 `^` 때문에 줄 머리에서만 시작하고 `(.+?)` 는 개행을 못 넘으므로, 이름(리터럴)은 그 줄(또는 공백만 있는
    줄들을 앞의 `\\s*` 가 건넌 뒤의 첫 내용 줄)에 **부분 문자열로** 있어야 한다. 그래서 이름이 나오는 줄의 머리에서
    `pattern.match` 를 하면 finditer 가 거기(또는 그 앞 빈 줄 머리)에서 얻는 매치와 group(1)·끝 위치가 같다(빈 줄 접두는
    group(0) 의 앞 공백만 다르고 호출자는 그것을 `(` 포함 여부·초기값 탐색에만 쓴다). finditer 처럼 앞 매치의 끝(`resume`)
    앞에서는 시작하지 않는다. 통단어(`\\b`) 판정은 **원 정규식에 맡긴다** — 후보를 미리 거르는 사전 검사는 결과에 기여하지
    않는 최적화였다(뮤테이션 생존으로 확인). `last_start` 도 같은 줄의 실패 매치를 반복하지 않는 최적화일 뿐이다.
    가드: `tests/unit/test_infer_type_scan_cache.py`(참조 구현 대조 + 고정 시드 무작위 대조).
    """
    if not name:
        yield from pattern.finditer(text)
        return
    resume = 0
    last_start = -1
    pos = 0
    while True:
        i = text.find(name, pos)
        if i < 0:
            return
        # 한 글자씩 전진한다 — `i + len(name)` 은 이름에 개행이 들어 자기겹침할 때 다른 줄의 후보를 건너뛴다(리뷰 I1 반례
        #   `text="a\nU8 a\nU8 a;"`, `name="a\nU8 a"`). 비용은 후보 줄 수에 비례하고 통단어 판정은 정규식 몫이다.
        pos = i + 1
        line_start = text.rfind("\n", 0, i) + 1
        if line_start < resume or line_start == last_start:
            continue
        last_start = line_start
        m = pattern.match(text, line_start)
        if m is None:
            continue
        yield m
        resume = m.end()


def _infer_type_from_file(
    file_path: str, name: str, *, cache: Optional[Dict[str, str]] = None
) -> Tuple[str, str]:
    """파일 원문에서 `name` 의 선언 타입(과 초기값)을 찾는 폴백 → `(타입, 초기값)`, 못 찾으면 `("", "")`.

    `cache` 는 **한 생성 실행 안**에서 파일 원문(상한 적용)을 재사용하는 dict({경로: 원문}) — 호출자가 만들고 버린다.
    ⚠ 실측(R52 N41, kjpds02_pv 2 루트 · 179 파일 · 3.4MB): 전역 25,007건이 전부 이 폴백을 탔고 **호출마다 파일을 다시
      읽어**(cloudium 모드에선 워커 IPC 소켓 연결) 777MB 를 옮겼다 — 소스 분석 491초 중 IPC 251초(51%). 같은 파일은 113개뿐.
      모듈 전역 캐시로 두지 않는다: 파일이 바뀐 뒤(SVN 갱신)에도 남는다. 기본값 None 은 옛 동작(매번 읽기) 그대로.
    """
    if not file_path or not name:
        return "", ""
    key = str(file_path)
    text = cache.get(key) if cache is not None else None
    if text is None:
        try:
            # ⚠ 상한을 여기 박아두면(옛 판 `200_000`) 선언이 파일 뒤쪽에 있는 전역은
            #   폴백조차 못 탄다. 상한은 `_SRC_READ_MAX_BYTES` 단일 출처(`_cap_and_decode`)를 따른다.
            text = _cap_and_decode(_read_bytes_resolver_aware(Path(file_path)))[0]
        except FileNotFoundError:
            text = ""        # 없는 파일 — 옛 동작(빈 원문)과 같고, 다시 읽어도 없으므로 캐시해도 된다
        except Exception:
            # (리뷰 W1) 일시 실패(워커 타임아웃·연결 거부 등)는 **캐시하지 않는다** — 빈 원문을 굳히면 그 파일의 나머지
            #   전역 전부가 조용히 타입 없음이 된다(재현: 첫 읽기만 실패시키면 3전역 전부 `("", "")`). 옛 판처럼 다음
            #   심볼에서 다시 읽는다. 반환값은 옛 판과 같다(`("", "")`).
            return "", ""
        # (R63 N70 리뷰 W1) 죽은 `#if 0` 분기의 선언이 **첫** 매치가 되어 산 전역의 Type/Reset 근거가 되지 않게 — 수집 루프가
        #   죽은 init 을 버린 뒤엔 이 폴백이 죽은 init 의 유일한 잔여 공급원이다. 캐시에도 가린 판을 담는다(소비자 둘 다 선언 탐색용).
        text = blank_dead_code(text)
        if cache is not None:
            cache[key] = text
    name_re = re.escape(name)
    try:
        pattern = re.compile(rf"^\s*(.+?)\b{name_re}\b\s*(=|\[|;)", re.M)
    except re.error:
        return "", ""
    for match in _iter_decl_matches(text, name, pattern):
        decl = match.group(0)
        if "(" in decl:
            continue
        head = match.group(1)
        head = re.sub(r"\b(static|extern|const|volatile)\b", "", head).strip()
        gtype = " ".join(head.split()).strip()
        init = ""
        init_match = re.search(rf"\b{name_re}\b\s*=\s*([^;]+)", decl)
        if init_match:
            init = init_match.group(1).strip()
        # ⚠ 모양이 아니면 **다음 후보로 넘어간다**. 파일 뒤쪽에 진짜 선언이 있을 수 있고,
        #   여기서 `}` 를 돌려주면 그게 그대로 설계서 Type 칸이 된다(`_is_type_head`).
        if gtype and _is_type_head(gtype):
            return gtype, init
    return "", ""


