"""report_gen.docx_builder - Auto-split from report_generator.py"""
# Re-import common dependencies
# Payload field name constants (canonical source: report_gen.uds_generator)
# Function-level (per-function, List[str]):
#   KEY_FN_GLOBALS = "globals_global"  — global vars used by the function
#   KEY_FN_STATICS = "globals_static"  — static vars used by the function
# Module-level (top-level payload, List[List[str]] 5-column table):
#   KEY_MOD_GLOBALS = "global_vars"    — global var definitions table
#   KEY_MOD_STATICS = "static_vars"    — static var definitions table
import json
import logging
import os
import re
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from report.constants import (
    GLOBALS_FORMAT_ORDER,
    GLOBALS_FORMAT_SEP,
    GLOBALS_FORMAT_WITH_LABELS,
    LOGIC_MAX_CHILDREN_DEFAULT,
    LOGIC_MAX_DEPTH_DEFAULT,
    LOGIC_MAX_GRANDCHILDREN_DEFAULT,
)
from report_gen.atomic_io import normalize_zip_member_times
from report_gen.function_analyzer import (
    FN_ROW_FULL,
    FN_ROW_GRID,
    FN_ROW_PAIR,
    PARAM_GRID_COLS,
    _build_function_info_layout,
    _enhance_description_text,
    _enhance_function_description,
    _fallback_function_description,
    _finalize_function_fields,
    _is_generic_description,
    _normalize_symbol_name,
    _parse_signature_outputs,
    _parse_signature_params,
    is_logic_diagram_header,
    is_logic_diagram_label,
    resolve_param_grid_entries,
)
from report_gen.provenance import (
    canonical_source,
    is_weak_source,
    reference_suds_may_override,
    unrecorded_source,
)
from report_gen.requirements import (
    _extract_doc_section,
    _extract_function_info_from_docx,
    _extract_sds_partition_map,
    _merge_sds_partition_map,
)
from report_gen.uds_text import (
    _ai_document_text,
    _ai_evidence_lines,
    _ai_quality_warnings,
    _apply_uds_rules,
    _merge_logic_ai_items,
    _merge_section_text,
)
from report_gen.utils import (
    _build_global_rows,
    _extract_call_names,
    _normalize_swufn_id,
    _safe_dict,
    _table_rows_from_texts,
    function_name_key,
)

_logger = logging.getLogger("report_generator")


def _count_duplicate_drawing_ids(doc: Any) -> Optional[int]:
    """문서 안 `wp:docPr/@id` 중복 건수(전체 − 서로 다른 값). 셀 수 없으면 None(미측정 — 0 과 구분)."""
    try:
        ids = [str(v) for v in doc.element.xpath(".//wp:docPr/@id")]
    except Exception:  # noqa: BLE001 — 공시 실패가 저장을 막아선 안 된다(None = 미측정)
        return None
    return len(ids) - len(set(ids))


def _save_docx(doc: Any, out: Path, output_path: str, stats: Dict[str, Any]) -> bool:
    """UDS DOCX 의 **유일한** 저장 경로 — `generate_uds_docx` 의 세 종결 분기(토큰 템플릿·구조 복제·무템플릿)가 다 여길 지난다.

    (R47-k N27-e) 저장 뒤 zip 멤버 시각을 고정한다. python-docx 는 멤버마다 저장 시각을 박아 같은 문서도
    저장할 때마다 바이트가 달랐다 — 검토 기록의 `output_sha256` 은 산출물 바이트이므로 "같은 입력 → 같은 문서"
    를 해시로 말하려면 여기서 지워야 한다. 정규화 실패는 warning 뿐, 산출물은 그대로 남는다.
    결과는 `stats["zip_time_normalized"]` 에 실어 gen_stats 사이드카로 남긴다(리뷰 W3) — 빌더는 로깅 설정이 없는
    서브프로세스에서 돌아 INFO 는 영영 안 찍히고 WARNING 도 성공 경로에선 버려진다. 문서 **안**에는 적을 수 없다
    (자기 해시를 바꾼다). 사이드카는 저장 뒤에 (다시) 쓴다.
    ⚠ 바이트 동일은 **구조 복제 분기**에서만 성립한다(리뷰 W2): 토큰 템플릿 분기(`{{generated_at}}`)와 무템플릿 분기
      (`Generated at:` 문단)는 payload 에 `generated_at` 이 없으면 벽시계를 본문에 박는다.
    """
    # (R53 리뷰 W3) 그림 id 유일성 공시 — `wp:docPr/@id` 는 문서 안에서 유일해야 한다(ECMA-376; 겹치면 Word 가 복구를 묻는다).
    #   `_PictureSink` 는 id 를 추적하므로 싱크를 거치지 않은 그림 삽입이 생기면 여기서 드러난다(문서 전체 xpath 1회 ≈ 2ms).
    #   막지 않고 적는다 — 저장을 막으면 문서 대신 아무것도 안 남고, 중복 자체는 Word 가 고칠 수 있다.
    stats["drawing_id_duplicates"] = _count_duplicate_drawing_ids(doc)
    if stats["drawing_id_duplicates"]:
        _logger.warning("그림 id(wp:docPr/@id) 중복 %d건 — 싱크를 거치지 않은 그림 삽입이 있다", stats["drawing_id_duplicates"])
    doc.save(str(out))
    t0 = _time.perf_counter()
    ok = normalize_zip_member_times(out)
    stats["zip_time_normalized"] = bool(ok)
    stats["zip_time_normalize_sec"] = round(_time.perf_counter() - t0, 2)
    _write_gen_stats(output_path, stats)
    return bool(ok)



def _add_docx_text_block(doc, text: str, max_lines: int = 8000) -> None:
    if not text:
        doc.add_paragraph("N/A")
        return
    lines = text.splitlines()
    for idx, ln in enumerate(lines):
        if max_lines and idx >= max_lines:
            doc.add_paragraph("...truncated...")
            break
        line = ln.rstrip()
        m = re.match(r"^(\d+(?:\.\d+)*)[\s\t]+(.+)$", line)
        if m:
            level = min(4, m.group(1).count(".") + 1)
            title = m.group(2).strip()
            if title:
                doc.add_heading(title, level=level)
                continue
        doc.add_paragraph(line)


def _build_uds_reference_lines(payload: Dict[str, Any]) -> List[str]:
    """Compose the Reference-section list from payload metadata.

    Priority:
      1. ``payload['reference_docs']`` — list of {title|file, version?} dicts
         (or bare strings). Most explicit; wins when callers curate references.
      2. ``payload['source_docs']`` — list of paths injected by the UDS
         pipeline (SRS files routed through ``req_file_paths`` / ``req_paths``).
      3. Legacy single-keys: srs_path / sds_path / hsis_path / stp_path.

    Returns a list of display lines (no trailing newlines). Empty list ⇒
    caller should substitute 'N/A'.
    """
    refs = payload.get("reference_docs") or []
    lines: List[str] = []
    if isinstance(refs, list) and refs:
        for i, r in enumerate(refs, 1):
            if isinstance(r, dict):
                title = str(r.get("title") or r.get("file") or r.get("name") or "").strip()
                if title:
                    ver = str(r.get("version") or "").strip()
                    lines.append(f"[{i}] {title}" + (f" (v{ver})" if ver else ""))
            elif isinstance(r, str):
                t = r.strip()
                if t:
                    lines.append(f"[{i}] {t}")
    if not lines:
        seen: set = set()
        src_docs = payload.get("source_docs") or []
        if isinstance(src_docs, list):
            for p in src_docs:
                s = str(p or "").strip()
                if not s or s in seen:
                    continue
                seen.add(s)
                lines.append(f"[{len(lines)+1}] {Path(s).name}")
        for key in ("srs_path", "sds_path", "hsis_path", "stp_path"):
            p = str(payload.get(key) or "").strip()
            if p and p not in seen:
                seen.add(p)
                lines.append(f"[{len(lines)+1}] {Path(p).name}")
    return lines


def _build_uds_reference_text(payload: Dict[str, Any]) -> str:
    """Backwards-compatible newline-joined form (used only as a display fallback)."""
    lines = _build_uds_reference_lines(payload)
    return "\n".join(lines) if lines else "N/A"


def _replace_reference_table_paragraph(doc, lines: List[str]) -> bool:
    """Replace ``{{REFERENCE_TABLE}}`` with a soft-wrapped list of references.

    Finds the paragraph whose text contains the token, removes its existing
    runs, and appends a single fresh ``<w:r>`` whose children alternate
    ``<w:t>`` / ``<w:br>`` so Word renders each entry on its own line. The
    OxmlElement path is used because ``Run.text = value`` strips every
    inline element (including ``<w:br>``) and would undo the break.

    Returns True when the token was found and replaced; False otherwise
    (caller can still fall back to flat-text substitution).
    """
    try:
        from docx.oxml import OxmlElement  # type: ignore
        from docx.oxml.ns import qn  # type: ignore
    except Exception:  # pragma: no cover — python-docx not importable
        return False

    token = "{{REFERENCE_TABLE}}"
    display = lines if lines else ["N/A"]

    for para in doc.paragraphs:
        if token not in (para.text or ""):
            continue
        # Remove every existing run element — keeps the paragraph's pPr
        # (numbering/style) intact.
        for run in list(para.runs):
            run._element.getparent().remove(run._element)

        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = display[0]
        r.append(t)
        for extra in display[1:]:
            r.append(OxmlElement("w:br"))
            t2 = OxmlElement("w:t")
            t2.set(qn("xml:space"), "preserve")
            t2.text = extra
            r.append(t2)
        para._element.append(r)
        return True
    return False


def _replace_docx_text(doc, replacements: Dict[str, str]) -> None:
    from docx.oxml.ns import qn  # type: ignore

    # (R53 N27-c) 원문 노드 선검사 — `paragraph.text` 는 run 마다 xpath 를 돌려 정본(셀 17만 개)에서 이 함수 하나가 21초였다.
    #   키의 첫 글자가 문단의 어느 `w:t` 에도 없으면 치환할 게 없다: python-docx 의 문단 텍스트는 `w:t` 의 부분집합에
    #   탭/개행/하이픈 문자(`w:tab`·`w:ptab`·`w:br`·`w:cr`·`w:noBreakHyphen` 요소)를 더한 것뿐이라(1.2.0 `CT_R.text` 원문 —
    #   리뷰 I3 대조: `w:sym`·`w:softHyphen`·`w:delText`·필드는 안 들어온다), 그 셋으로 시작하는 키가 있으면 선검사를 끈다.
    #   결과는 같고(선검사는 "확실히 없음" 만 거른다) 읽는 문단만 준다.
    _first = {k[:1] for k in replacements if k}
    _prescan = bool(_first) and all(not ch.isspace() and ch != "-" for ch in _first)
    _w_t = qn("w:t")

    def _replace_in_paragraph(paragraph):
        if _prescan and not any(ch in (t.text or "") for t in paragraph._p.iter(_w_t) for ch in _first):
            return
        full = paragraph.text
        if not full:
            return
        changed = full
        for key, val in replacements.items():
            if key in changed:
                changed = changed.replace(key, val)
        if changed == full:
            return
        runs = paragraph.runs
        if not runs:
            paragraph.text = changed
            return
        joined = "".join(r.text for r in runs)
        if joined != full:
            paragraph.text = changed
            return
        for key, val in replacements.items():
            if key not in joined:
                continue
            cursor = 0
            for run in runs:
                rt = run.text
                start = cursor
                end = cursor + len(rt)
                cursor = end
                seg = joined[start:end]
                if key in seg:
                    run.text = seg.replace(key, val)
                    joined = "".join(r.text for r in runs)
                    break
            else:
                idx = joined.find(key)
                if idx < 0:
                    continue
                new_joined = joined[:idx] + val + joined[idx + len(key):]
                pos = 0
                for run in runs:
                    rlen = len(run.text)
                    run.text = new_joined[pos:pos + rlen] if pos + rlen <= len(new_joined) else new_joined[pos:]
                    pos += rlen
                if pos < len(new_joined):
                    runs[-1].text += new_joined[pos:]
                joined = "".join(r.text for r in runs)

    for paragraph in doc.paragraphs:
        _replace_in_paragraph(paragraph)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    _replace_in_paragraph(paragraph)
    for section in doc.sections:
        for hf in [section.header, section.footer]:
            if not hf or not hasattr(hf, "paragraphs"):
                continue
            for paragraph in hf.paragraphs:
                _replace_in_paragraph(paragraph)


def _add_docx_bullets(doc, text: str) -> None:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        doc.add_paragraph("N/A")
        return
    for ln in lines:
        item = ln.lstrip("-* ").strip()
        if not item:
            continue
        try:
            doc.add_paragraph(item, style="List Bullet")
        except Exception:
            doc.add_paragraph(item)


def _add_docx_lines(doc, text: str) -> None:
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    if not lines:
        doc.add_paragraph("N/A")
        return
    for ln in lines:
        doc.add_paragraph(ln)


def _add_docx_toc(doc) -> None:
    try:
        from docx.oxml import OxmlElement  # type: ignore
        from docx.oxml.ns import qn  # type: ignore
    except Exception:
        return
    paragraph = doc.add_paragraph()
    run = paragraph.add_run()
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), 'TOC \\o "1-3" \\h \\z \\u')
    run._r.append(fld)


def _render_logic_flow_diagram(
    func_name: str,
    flow_nodes: List[Dict[str, Any]],
    out_path: Path,
    all_calls: Optional[List[str]] = None,
    call_map: Optional[Dict[str, List[str]]] = None,
) -> Optional[str]:
    """Render an adaptive logic diagram based on extracted control flow."""
    if not func_name:
        func_name = "Function"
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception:
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        font = ImageFont.truetype("arial.ttf", 12)
        font_sm = ImageFont.truetype("arial.ttf", 10)
        font_title = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 12)
            font_sm = ImageFont.truetype("DejaVuSans.ttf", 10)
            font_title = ImageFont.truetype("DejaVuSans.ttf", 14)
        except Exception:
            font = ImageFont.load_default()
            font_sm = font
            font_title = font

    COLORS = {
        "start": "#E3F2FD", "end": "#E3F2FD",
        "call": "#E8F5E9", "call_outline": "#388E3C",
        "if_diamond": "#FFF8E1", "if_outline": "#F57F17",
        "true_box": "#E8F5E9", "false_box": "#FFEBEE",
        "switch_diamond": "#F3E5F5", "switch_outline": "#7B1FA2",
        "case_box": "#EDE7F6",
        "loop_box": "#E0F7FA", "loop_outline": "#00838F",
        "return_box": "#FCE4EC", "return_outline": "#C62828",
        "assign": "#F5F5F5",
        "arrow": "#37474F",
        "bg": "#FFFFFF",
    }

    W = 1200
    MARGIN_X = 60
    NODE_W = 260
    NODE_H = 40
    DIAMOND_W = 220
    DIAMOND_H = 90
    GAP_Y = 20
    BRANCH_GAP_X = 80
    MAX_VISIBLE_NODES = 80

    canvas_items: List[Dict[str, Any]] = []
    _uid = [0]

    def _next_id():
        _uid[0] += 1
        return _uid[0]

    def _add(kind: str, x: int, y: int, w: int, h: int, **kw):
        item = {"id": _next_id(), "kind": kind, "x": x, "y": y, "w": w, "h": h}
        item.update(kw)
        canvas_items.append(item)
        return item

    def _trunc(text: str, maxlen: int = 40) -> str:
        text = " ".join(str(text or "").replace("\n", " ").split()).strip()
        if len(text) > maxlen:
            return text[:maxlen - 3] + "..."
        return text

    def _layout_flow(nodes: List[Dict[str, Any]], cx: int, y: int,
                     avail_w: int, depth: int = 0) -> int:
        """Layout flow nodes starting at center x=cx, top y. Returns bottom y."""
        if depth > 4 or not nodes:
            return y
        node_count = [0]

        for node in nodes:
            if node_count[0] >= MAX_VISIBLE_NODES:
                _add("ellipse", cx - 60, y, 120, 30, text="...", fill=COLORS["assign"])
                y += 30 + GAP_Y
                break
            node_count[0] += 1
            ntype = node.get("type", "")

            if ntype == "call":
                nw = min(NODE_W, avail_w - 20)
                _add("rect", cx - nw // 2, y, nw, NODE_H,
                     text=node["name"], fill=COLORS["call"],
                     outline=COLORS["call_outline"], radius=6)
                y += NODE_H + GAP_Y

            elif ntype == "return":
                nw = min(NODE_W, avail_w - 20)
                val = node.get("value", "")
                label = f"return {val}" if val else "return"
                _add("rounded", cx - nw // 2, y, nw, 36,
                     text=_trunc(label, 36), fill=COLORS["return_box"],
                     outline=COLORS["return_outline"], radius=16)
                y += 36 + GAP_Y

            elif ntype == "assign":
                nw = min(NODE_W - 20, avail_w - 20)
                _add("rect", cx - nw // 2, y, nw, 32,
                     text=_trunc(node.get("text", ""), 36), fill=COLORS["assign"],
                     outline="#9E9E9E", radius=4)
                y += 32 + GAP_Y

            elif ntype == "if":
                cond = _trunc(node.get("condition", "?"), 50)
                dw = min(DIAMOND_W, avail_w - 40)
                dh = DIAMOND_H
                _add("diamond", cx - dw // 2, y, dw, dh,
                     text=cond, fill=COLORS["if_diamond"],
                     outline=COLORS["if_outline"])
                dia_bottom = y + dh

                true_body = node.get("true_body", [])
                false_body = node.get("false_body", [])

                branch_w = max(180, (avail_w - BRANCH_GAP_X) // 2)
                left_cx = cx - branch_w // 2 - BRANCH_GAP_X // 2
                right_cx = cx + branch_w // 2 + BRANCH_GAP_X // 2

                branch_top = dia_bottom + GAP_Y + 15
                _add("arrow", cx - dw // 2, y + dh // 2, 0, 0,
                     to_x=left_cx, to_y=branch_top, label="Y")
                _add("arrow", cx + dw // 2, y + dh // 2, 0, 0,
                     to_x=right_cx, to_y=branch_top, label="N")

                if true_body:
                    left_bottom = _layout_flow(true_body, left_cx, branch_top,
                                               branch_w, depth + 1)
                else:
                    _add("rect", left_cx - 60, branch_top, 120, 28,
                         text="(pass)", fill="#FAFAFA", outline="#BDBDBD", radius=4)
                    left_bottom = branch_top + 28

                if false_body:
                    right_bottom = _layout_flow(false_body, right_cx, branch_top,
                                                branch_w, depth + 1)
                else:
                    _add("rect", right_cx - 60, branch_top, 120, 28,
                         text="(pass)", fill="#FAFAFA", outline="#BDBDBD", radius=4)
                    right_bottom = branch_top + 28

                merge_y = max(left_bottom, right_bottom) + GAP_Y
                _add("arrow", left_cx, left_bottom, 0, 0,
                     to_x=cx, to_y=merge_y, label="")
                _add("arrow", right_cx, right_bottom, 0, 0,
                     to_x=cx, to_y=merge_y, label="")
                y = merge_y

            elif ntype == "switch":
                expr = _trunc(node.get("expr", "?"), 46)
                dw = min(DIAMOND_W + 40, avail_w - 40)
                dh = DIAMOND_H
                _add("diamond", cx - dw // 2, y, dw, dh,
                     text=f"switch({expr})", fill=COLORS["switch_diamond"],
                     outline=COLORS["switch_outline"])
                dia_bottom = y + dh

                cases = node.get("cases", [])[:6]
                default_calls = node.get("default_calls", [])[:3]
                n_branches = len(cases) + (1 if default_calls else 0)
                if n_branches == 0:
                    y = dia_bottom + GAP_Y
                    continue

                case_w = min(180, max(100, (avail_w - 40) // max(n_branches, 1)))
                total_w = n_branches * case_w + (n_branches - 1) * 10
                start_x = cx - total_w // 2
                branch_top = dia_bottom + GAP_Y + 15
                bottoms = []

                for ci, case in enumerate(cases):
                    bx = start_x + ci * (case_w + 10)
                    bcx = bx + case_w // 2
                    label = _trunc(case.get("label", "?"), 20)
                    _add("arrow", cx, dia_bottom, 0, 0,
                         to_x=bcx, to_y=branch_top, label=label)
                    call_y = branch_top
                    for call_name in case.get("calls", [])[:3]:
                        _add("rect", bx, call_y, case_w, 32,
                             text=_trunc(call_name, 22), fill=COLORS["case_box"],
                             outline=COLORS["switch_outline"], radius=4)
                        call_y += 32 + 6
                    bottoms.append(call_y)

                if default_calls:
                    di = len(cases)
                    bx = start_x + di * (case_w + 10)
                    bcx = bx + case_w // 2
                    _add("arrow", cx, dia_bottom, 0, 0,
                         to_x=bcx, to_y=branch_top, label="default")
                    call_y = branch_top
                    for call_name in default_calls[:3]:
                        _add("rect", bx, call_y, case_w, 32,
                             text=_trunc(call_name, 22), fill="#FBE9E7",
                             outline=COLORS["switch_outline"], radius=4)
                        call_y += 32 + 6
                    bottoms.append(call_y)

                merge_y = max(bottoms) + GAP_Y if bottoms else dia_bottom + GAP_Y
                for ci in range(n_branches):
                    bx = start_x + ci * (case_w + 10)
                    bcx = bx + case_w // 2
                    _add("arrow", bcx, bottoms[ci] if ci < len(bottoms) else merge_y, 0, 0,
                         to_x=cx, to_y=merge_y, label="")
                y = merge_y

            elif ntype == "loop":
                cond = _trunc(node.get("condition", ""), 46)
                kind = node.get("kind", "while")
                loop_label = f"{kind}({cond})" if cond else kind
                nw = min(NODE_W + 40, avail_w - 20)
                _add("loop_header", cx - nw // 2, y, nw, NODE_H,
                     text=_trunc(loop_label, 46), fill=COLORS["loop_box"],
                     outline=COLORS["loop_outline"], radius=8)
                header_bottom = y + NODE_H

                body_nodes = node.get("body", [])
                if body_nodes:
                    body_top = header_bottom + GAP_Y
                    inner_w = avail_w - 40
                    body_bottom = _layout_flow(body_nodes, cx, body_top,
                                               inner_w, depth + 1)
                    _add("loop_back", cx + nw // 2 + 10, header_bottom, 0, 0,
                         to_x=cx + nw // 2 + 10, to_y=y + NODE_H // 2,
                         body_bottom=body_bottom)
                    y = body_bottom + GAP_Y
                else:
                    y = header_bottom + GAP_Y

        return y

    # --- Build layout ---
    start_y = 20
    title_h = 44
    _add("ellipse", W // 2 - 180, start_y, 360, title_h,
         text=func_name, fill=COLORS["start"], outline="#1565C0")

    flow_top = start_y + title_h + GAP_Y
    cx = W // 2

    if not flow_nodes:
        calls = all_calls or []
        if calls:
            cy = flow_top
            for c in calls[:10]:
                _add("rect", cx - NODE_W // 2, cy, NODE_W, NODE_H,
                     text=c, fill=COLORS["call"], outline=COLORS["call_outline"], radius=6)
                if cy > flow_top:
                    pass  # arrows handled in render
                cy += NODE_H + GAP_Y
            flow_bottom = cy
        else:
            _add("rect", cx - 100, flow_top, 200, 36,
                 text="(no branch / direct)", fill="#FAFAFA", outline="#BDBDBD", radius=4)
            flow_bottom = flow_top + 36 + GAP_Y
    else:
        flow_bottom = _layout_flow(flow_nodes, cx, flow_top, W - MARGIN_X * 2)

    end_y = flow_bottom + GAP_Y
    _add("ellipse", cx - 120, end_y, 240, 36,
         text="End", fill=COLORS["end"], outline="#1565C0")
    total_h = end_y + 36 + 30

    # --- Pagination note: if total_h > 2000, diagram spans multiple pages ---
    # The full image is still created as a single file; the DOCX renderer
    # will scale it to fit page width, causing it to span across pages
    # automatically when the image is tall enough.

    # --- Render ---
    img = Image.new("RGB", (W, max(400, total_h)), COLORS["bg"])
    draw = ImageDraw.Draw(img)

    def _measure(s, f=None):
        f = f or font
        try:
            return draw.textlength(str(s or ""), font=f)
        except Exception:
            return len(str(s or "")) * 7

    def _draw_text_centered(box, text, f=None):
        f = f or font
        x1, y1, x2, y2 = box
        lines = str(text or "").split("\n")
        lh = 15
        total = len(lines) * lh
        ty = y1 + max(2, (y2 - y1 - total) // 2)
        for ln in lines:
            tw = _measure(ln, f)
            tx = x1 + max(4, (x2 - x1 - tw) // 2)
            draw.text((tx, ty), ln, fill="black", font=f)
            ty += lh

    def _draw_arrow(x1, y1, x2, y2, color=COLORS["arrow"]):
        draw.line([(x1, y1), (x2, y2)], fill=color, width=2)
        dx = x2 - x1
        dy = y2 - y1
        length = max(1, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / length, dy / length
        ax, ay = x2 - ux * 8, y2 - uy * 8
        px, py = -uy * 5, ux * 5
        draw.polygon([(x2, y2), (int(ax + px), int(ay + py)),
                       (int(ax - px), int(ay - py))], fill=color)

    prev_center = None
    for item in canvas_items:
        k = item["kind"]
        x, y, w, h = item["x"], item["y"], item["w"], item["h"]

        if k == "ellipse":
            draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2,
                                   fill=item.get("fill", "#FFF"),
                                   outline=item.get("outline", "black"), width=2)
            _draw_text_centered((x, y, x + w, y + h), item.get("text", ""),
                                font_title if h > 40 else font)
            if prev_center and k != "arrow":
                _draw_arrow(prev_center[0], prev_center[1], x + w // 2, y)
            prev_center = (x + w // 2, y + h)

        elif k == "rect":
            r = item.get("radius", 0)
            if r:
                draw.rounded_rectangle([x, y, x + w, y + h], radius=r,
                                       fill=item.get("fill", "#FFF"),
                                       outline=item.get("outline", "black"), width=1)
            else:
                draw.rectangle([x, y, x + w, y + h],
                               fill=item.get("fill", "#FFF"),
                               outline=item.get("outline", "black"), width=1)
            _draw_text_centered((x, y, x + w, y + h), item.get("text", ""))

        elif k == "rounded":
            r = item.get("radius", 16)
            draw.rounded_rectangle([x, y, x + w, y + h], radius=r,
                                   fill=item.get("fill", "#FFF"),
                                   outline=item.get("outline", "black"), width=2)
            _draw_text_centered((x, y, x + w, y + h), item.get("text", ""))

        elif k == "diamond":
            cx_d = x + w // 2
            cy_d = y + h // 2
            pts = [(cx_d, y), (x + w, cy_d), (cx_d, y + h), (x, cy_d)]
            draw.polygon(pts, fill=item.get("fill", "#FFF"),
                         outline=item.get("outline", "black"))
            draw.polygon(pts, outline=item.get("outline", "black"))
            _draw_text_centered((x + 15, y + 8, x + w - 15, y + h - 8),
                                item.get("text", ""), font_sm)

        elif k == "loop_header":
            r = item.get("radius", 8)
            draw.rounded_rectangle([x, y, x + w, y + h], radius=r,
                                   fill=item.get("fill", "#FFF"),
                                   outline=item.get("outline", "black"), width=2)
            draw.rounded_rectangle([x + 2, y + 2, x + w - 2, y + h - 2], radius=r,
                                   fill=None,
                                   outline=item.get("outline", "black"), width=1)
            _draw_text_centered((x, y, x + w, y + h), item.get("text", ""))

        elif k == "arrow":
            to_x = item.get("to_x", x)
            to_y = item.get("to_y", y)
            label = item.get("label", "")
            _draw_arrow(x, y, to_x, to_y)
            if label:
                mx = (x + to_x) // 2
                my = (y + to_y) // 2
                bw = max(20, int(_measure(label, font_sm)) + 8)
                draw.rounded_rectangle([mx - bw // 2, my - 10, mx + bw // 2, my + 8],
                                       radius=4, fill="white", outline="#9E9E9E")
                tw = _measure(label, font_sm)
                draw.text((mx - tw // 2, my - 8), label, fill="black", font=font_sm)

        elif k == "loop_back":
            to_x = item.get("to_x", x)
            to_y = item.get("to_y", y)
            bb = item.get("body_bottom", y + 40)
            lx = to_x
            draw.line([(lx, y), (lx, bb + 10)], fill=COLORS["loop_outline"], width=2)
            draw.line([(lx, bb + 10), (lx - 20, bb + 10)], fill=COLORS["loop_outline"], width=2)
            draw.line([(lx, y), (lx - 20, y)], fill=COLORS["loop_outline"], width=2)
            _draw_arrow(lx - 20, y, lx - 20, to_y)

    # Draw sequential arrows between vertically-adjacent same-column items,
    # but only if no explicit arrow already targets the next node.
    arrow_targets = set()
    for it in canvas_items:
        if it["kind"] == "arrow":
            arrow_targets.add((it.get("to_x", 0), it.get("to_y", 0)))

    seq_items = [it for it in canvas_items
                 if it["kind"] in ("ellipse", "rect", "rounded", "loop_header")
                 and it.get("text") != "(pass)"]
    for i in range(len(seq_items) - 1):
        cur = seq_items[i]
        nxt = seq_items[i + 1]
        cur_bx = cur["x"] + cur["w"] // 2
        cur_by = cur["y"] + cur["h"]
        nxt_tx = nxt["x"] + nxt["w"] // 2
        nxt_ty = nxt["y"]
        if abs(cur_bx - nxt_tx) < 8 and nxt_ty > cur_by and nxt_ty - cur_by < 120:
            has_target = any(abs(tx - nxt_tx) < 20 and abs(ty - nxt_ty) < 20
                             for tx, ty in arrow_targets)
            if not has_target:
                _draw_arrow(cur_bx, cur_by, nxt_tx, nxt_ty)

    if total_h < img.size[1] - 60:
        img = img.crop((0, 0, W, total_h))

    img.save(str(out_path))
    return str(out_path)


def _render_logic_text_image(text: str, out_path: Path) -> Optional[str]:
    if not text:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1200, 700), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 13)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 13)
        except Exception:
            font = ImageFont.load_default()
    try:
        draw.textlength
        def measure(s):
            txt = str(s or "").replace("\r", " ").replace("\n", " ")
            try:
                return draw.textlength(txt, font=font)  # type: ignore
            except Exception:
                return len(txt) * 6
    except Exception:
        measure = lambda s: len(s) * 6
    def _wrap_lines(text_block: str, max_width: int) -> str:
        lines = []
        for raw in text_block.splitlines():
            line = raw
            while line:
                if measure(line) <= max_width:
                    lines.append(line)
                    break
                cut = max(10, int(len(line) * (max_width / max(1, measure(line)))))
                lines.append(line[:cut])
                line = line[cut:]
        return "\n".join(lines)
    margin = 10
    wrapped = _wrap_lines(text, img.size[0] - margin * 2)
    draw.multiline_text((margin, margin), wrapped, fill="black", font=font, spacing=4)
    img.save(str(out_path))
    return str(out_path)


def _render_call_graph_image(
    func_name: str,
    calls: List[str],
    call_map: Optional[Dict[str, List[str]]],
    out_path: Path,
    max_children: int = 3,
    max_grandchildren: int = 2,
    max_depth: int = LOGIC_MAX_DEPTH_DEFAULT,
    module_map: Optional[Dict[str, str]] = None,
    condition_text: str = "",
    true_path_text: str = "",
    false_path_text: str = "",
    return_path_text: str = "",
    error_path_text: str = "",
) -> Optional[str]:
    if not func_name:
        func_name = "Function"
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception:
        _logger.warning("PIL not available, skipping call graph image for %s", func_name)
        return None
    def _normalize_condition_label(text: str) -> str:
        s = " ".join(str(text or "").replace("\n", " ").split()).strip()
        if not s:
            return ""
        s = re.sub(r"\b([A-Za-z_]\w*)\s*!=\s*0\b", r"\1", s)
        s = re.sub(r"\b([A-Za-z_]\w*)\s*==\s*0\b", r"!\1", s)
        s = s.replace("&&", " AND ").replace("||", " OR ")
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) > 40:
            s = s[:37].rstrip() + "..."
        return s

    def _branch_label(name: str) -> str:
        nm = str(name or "").strip()
        if not nm:
            return "N/A"
        if "(" in nm:
            m = re.search(r"\b([A-Za-z_]\w*)\s*\(", nm)
            nm = m.group(1) if m else nm
        nm = re.sub(r"^[sgu]_", "", nm)
        nm = nm.replace("_", " ")
        nm = re.sub(r"\s+", " ", nm).strip()
        if nm:
            nm = nm[0].upper() + nm[1:]
        return nm or "N/A"

    def _branch_path_label(path_text: str, fallback_name: str, fallback_default: str) -> str:
        raw = str(path_text or "").strip()
        if raw:
            first = re.split(r"[\n,;]", raw)[0].strip()
            if first:
                return _branch_label(first)
        if fallback_name:
            return _branch_label(fallback_name)
        return fallback_default

    def _derive_condition_label() -> str:
        if str(condition_text or "").strip():
            return _normalize_condition_label(condition_text)
        fn = str(func_name or "").lower()
        if "init" in fn:
            return "Init path selection"
        if "reset" in fn:
            return "Reset condition"
        if any(k in fn for k in ["check", "diag", "valid"]):
            return "Check / validation"
        if any(k in fn for k in ["state", "mode", "ctrl"]):
            return "State / mode branch"
        if children:
            sample = ", ".join([_branch_label(x) for x in children[:2]])
            return f"Call dispatch ({sample})" if sample else "Call dispatch"
        if return_path_text or error_path_text:
            return "Return / error branch"
        return "Condition unavailable"

    children = [c for c in calls if c][:max_children]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    width = 1420
    base_height = 980
    extra_depth = max(0, max_depth - 1)
    est_height = base_height + extra_depth * 180
    height = max(base_height, est_height)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 12)
        except Exception:
            font = ImageFont.load_default()
    try:
        draw.textlength
        def measure(s):
            txt = str(s or "").replace("\r", " ").replace("\n", " ")
            try:
                return draw.textlength(txt, font=font)  # type: ignore
            except Exception:
                return len(txt) * 6
    except Exception:
        measure = lambda s: len(s) * 6
    def _fit_text(text: str, max_width: int) -> str:
        text = " ".join(str(text or "").splitlines()).strip()
        if measure(text) <= max_width:
            return text
        suffix = "..."
        trimmed = text
        while trimmed and measure(trimmed + suffix) > max_width:
            trimmed = trimmed[:-1]
        return trimmed + suffix if trimmed else text

    def _wrap_for_box(text: str, max_width: int, max_lines: int = 2) -> str:
        words = str(text or "").split()
        if not words:
            return ""
        lines: List[str] = []
        cur = words[0]
        for w in words[1:]:
            cand = f"{cur} {w}"
            if measure(cand) <= max_width:
                cur = cand
            else:
                lines.append(cur)
                cur = w
                if len(lines) >= max_lines - 1:
                    break
        lines.append(cur)
        lines = lines[:max_lines]
        if len(words) > 1 and len(lines) == max_lines:
            merged = " ".join(lines)
            if len(merged.split()) < len(words):
                lines[-1] = _fit_text(lines[-1], max_width)
        return "\n".join(lines)

    def _draw_centered_text(box, text: str, max_lines: int = 2):
        x1, y1, x2, y2 = box
        wrapped = _wrap_for_box(text, max(30, (x2 - x1) - 20), max_lines=max_lines)
        lines = wrapped.splitlines() if wrapped else [""]
        line_h = 15
        total_h = len(lines) * line_h
        ty = y1 + max(4, ((y2 - y1) - total_h) // 2)
        for ln in lines:
            tw = measure(ln)
            tx = x1 + max(8, int(((x2 - x1) - tw) // 2))
            draw.text((tx, ty), ln, fill="black", font=font)
            ty += line_h

    def _rounded_rect(box, radius=6, fill=None, outline="black", width=1):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def _ellipse(box, text, fill="#FFFFFF"):
        _rounded_rect(box, radius=22, fill=fill)
        _draw_centered_text(box, text, max_lines=2)

    def _diamond(center, w, h, text):
        cx, cy = center
        points = [(cx, cy - h // 2), (cx + w // 2, cy), (cx, cy + h // 2), (cx - w // 2, cy)]
        draw.polygon(points, fill="#FFFFFF", outline="black")
        _draw_centered_text((cx - w // 2 + 10, cy - h // 2 + 8, cx + w // 2 - 10, cy + h // 2 - 8), text, max_lines=3)

    def _arrow(p1, p2):
        draw.line([p1, p2], fill="black", width=2)
        x2, y2 = p2
        draw.polygon([(x2, y2), (x2 - 8, y2 - 5), (x2 - 8, y2 + 5)], fill="black")

    def _arrow_with_label(p1, p2, label: str, side: str = "center"):
        _arrow(p1, p2)
        mx = (p1[0] + p2[0]) // 2
        my = (p1[1] + p2[1]) // 2
        if side == "left":
            lx, ly = mx - 48, my - 20
        elif side == "right":
            lx, ly = mx + 12, my - 20
        else:
            lx, ly = mx - 18, my - 20
        bw = max(28, int(measure(label)) + 10)
        bh = 18
        _rounded_rect((lx - 4, ly - 2, lx - 4 + bw, ly - 2 + bh), radius=4, fill="#FFFFFF")
        draw.text((lx, ly), label, fill="black", font=font)

    def _pick_target_name(path_text: str, fallback: str) -> str:
        names = _extract_call_names(str(path_text or ""))
        if names:
            return str(names[0]).strip()
        return str(fallback or "").strip()

    def _draw_summary_panel(x: int, y: int, w: int, h: int) -> None:
        _rounded_rect((x, y, x + w, y + h), radius=8, fill="#F8F9FA")
        draw.text((x + 10, y + 8), "Flow Summary", fill="black", font=font)
        lines: List[str] = []
        lines.append(f"- Condition: {_derive_condition_label()}")
        if children:
            for idx, nm in enumerate(children[:6], start=1):
                lines.append(f"- Call {idx}: {_branch_label(nm)}")
        else:
            lines.append("- Call: N/A")
        if return_path_text:
            lines.append(f"- Return: {_branch_label(return_path_text)}")
        if error_path_text:
            lines.append(f"- Error: {_branch_label(error_path_text)}")
        ly = y + 30
        for ln in lines[:10]:
            draw.text((x + 10, ly), _fit_text(ln, w - 16), fill="black", font=font)
            ly += 16

    center_x = width // 2
    start_y = 26
    ellipse_w, ellipse_h = 520, 50
    proc_w, proc_h = 620, 60
    dia_w, dia_h = 260, 120
    branch_w, branch_h = 400, 64

    _ellipse((center_x - ellipse_w // 2, start_y, center_x + ellipse_w // 2, start_y + ellipse_h), func_name, fill="#F7FBFF")

    proc_y = start_y + 80
    _rounded_rect((center_x - proc_w // 2, proc_y, center_x + proc_w // 2, proc_y + proc_h), radius=8, fill="#EEF3F8")
    _draw_centered_text((center_x - proc_w // 2, proc_y, center_x + proc_w // 2, proc_y + proc_h), func_name, max_lines=2)
    _arrow((center_x, start_y + ellipse_h), (center_x, proc_y))

    dia_y = proc_y + 90
    _diamond(
        (center_x, dia_y + dia_h // 2),
        dia_w,
        dia_h,
        _fit_text(_derive_condition_label(), dia_w - 16),
    )
    _arrow((center_x, proc_y + proc_h), (center_x, dia_y))

    yes_label = _branch_path_label(true_path_text, children[0] if children else "", "Yes Path")
    no_label = _branch_path_label(false_path_text, children[1] if len(children) > 1 else "", "No Path")

    branch_gap = max(320, branch_w // 2 + 150)
    left_x = center_x - branch_gap
    right_x = center_x + branch_gap
    branch_y = dia_y + 138

    _rounded_rect((left_x - branch_w // 2, branch_y, left_x + branch_w // 2, branch_y + branch_h), radius=8, fill="#E8F5E9")
    _draw_centered_text((left_x - branch_w // 2, branch_y, left_x + branch_w // 2, branch_y + branch_h), yes_label, max_lines=2)

    _rounded_rect((right_x - branch_w // 2, branch_y, right_x + branch_w // 2, branch_y + branch_h), radius=8, fill="#FFF3E0")
    _draw_centered_text((right_x - branch_w // 2, branch_y, right_x + branch_w // 2, branch_y + branch_h), no_label, max_lines=2)

    _arrow_with_label((center_x - dia_w // 2, dia_y + dia_h // 2), (left_x + branch_w // 2, branch_y), "Yes", side="left")
    _arrow_with_label((center_x + dia_w // 2, dia_y + dia_h // 2), (right_x - branch_w // 2, branch_y), "No", side="right")

    # Depth-2 call expansion for better call-flow readability.
    depth2_bottom = branch_y + branch_h
    if call_map and max_depth >= 2:
        yes_target = _pick_target_name(true_path_text, children[0] if children else "")
        no_target = _pick_target_name(false_path_text, children[1] if len(children) > 1 else "")
        yes_next = [str(x).strip() for x in (call_map.get(yes_target, []) or []) if str(x).strip()][:max_grandchildren]
        no_next = [str(x).strip() for x in (call_map.get(no_target, []) or []) if str(x).strip()][:max_grandchildren]

        def _draw_depth2(x_center: int, labels: List[str], fill_color: str) -> int:
            if not labels:
                return branch_y + branch_h
            y0 = branch_y + 86
            h2 = 46
            w2 = 300
            for i, nm in enumerate(labels):
                y = y0 + i * 58
                _rounded_rect((x_center - w2 // 2, y, x_center + w2 // 2, y + h2), radius=6, fill=fill_color)
                _draw_centered_text((x_center - w2 // 2, y, x_center + w2 // 2, y + h2), _branch_label(nm), max_lines=2)
                if i == 0:
                    _arrow((x_center, branch_y + branch_h), (x_center, y))
                else:
                    _arrow((x_center, y - 14), (x_center, y))
            return y0 + (len(labels) - 1) * 58 + h2

        depth2_bottom = max(
            _draw_depth2(left_x, yes_next, "#E3F2FD"),
            _draw_depth2(right_x, no_next, "#E3F2FD"),
        )
        if max_depth >= 3:
            def _draw_depth3(seed_names: List[str], x_center: int) -> int:
                d3: List[str] = []
                for seed in seed_names[: max_grandchildren]:
                    nxt = [str(x).strip() for x in (call_map.get(seed, []) or []) if str(x).strip()]
                    for n in nxt[:2]:
                        if n not in d3:
                            d3.append(n)
                if not d3:
                    return depth2_bottom
                y0 = depth2_bottom + 48
                h3 = 40
                w3 = 250
                for i, nm in enumerate(d3[:4]):
                    y = y0 + i * 48
                    _rounded_rect((x_center - w3 // 2, y, x_center + w3 // 2, y + h3), radius=5, fill="#EAF4FF")
                    _draw_centered_text((x_center - w3 // 2, y, x_center + w3 // 2, y + h3), _branch_label(nm), max_lines=2)
                    if i == 0:
                        _arrow((x_center, depth2_bottom), (x_center, y))
                return y0 + (min(len(d3), 4) - 1) * 48 + h3

            depth2_bottom = max(depth2_bottom, _draw_depth3(yes_next, left_x), _draw_depth3(no_next, right_x))

    # Add side summary panel for readability in large call graphs.
    _draw_summary_panel(20, 160, 300, 260)

    end_y = depth2_bottom + 92
    return_text = str(return_path_text or "").strip()
    error_text = str(error_path_text or "").strip()
    has_return = bool(return_text)
    has_error = bool(error_text)

    if has_return and has_error:
        _ellipse((center_x - 520, end_y, center_x - 160, end_y + ellipse_h), _fit_text(return_text, 320))
        _rounded_rect((center_x + 160, end_y, center_x + 520, end_y + ellipse_h), radius=16, fill="#FFEBEE")
        _draw_centered_text((center_x + 160, end_y, center_x + 520, end_y + ellipse_h), error_text, max_lines=2)
        _arrow((left_x, depth2_bottom), (center_x - 340, end_y))
        _arrow((right_x, depth2_bottom), (center_x + 340, end_y))
    elif has_return or has_error:
        terminal = return_text if has_return else error_text
        fill = "#FFFFFF" if has_return else "#FFEBEE"
        _rounded_rect((center_x - ellipse_w // 2, end_y, center_x + ellipse_w // 2, end_y + ellipse_h), radius=16, fill=fill)
        _draw_centered_text((center_x - ellipse_w // 2, end_y, center_x + ellipse_w // 2, end_y + ellipse_h), terminal, max_lines=2)
        _arrow((left_x, depth2_bottom), (center_x - 80, end_y))
        _arrow((right_x, depth2_bottom), (center_x + 80, end_y))
    else:
        _ellipse((center_x - ellipse_w // 2, end_y, center_x + ellipse_w // 2, end_y + ellipse_h), "End")
        _arrow((left_x, depth2_bottom), (center_x - 80, end_y))
        _arrow((right_x, depth2_bottom), (center_x + 80, end_y))
    final_needed = end_y + ellipse_h + 40
    if final_needed > height:
        new_img = Image.new("RGB", (width, final_needed), "white")
        new_img.paste(img, (0, 0))
        img = new_img
    elif final_needed < height - 100:
        img = img.crop((0, 0, width, final_needed))
    img.save(str(out_path))
    return str(out_path)


def _render_unit_structure_image(
    module_label: str,
    interfaces: List[str],
    internals: List[str],
    out_path: Path,
) -> Optional[str]:
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception:
        _logger.warning("PIL not available, skipping structure image for %s", module_label)
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    width = 1600
    height = 1000
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 12)
        except Exception:
            font = ImageFont.load_default()
    try:
        draw.textlength
        measure = lambda s: draw.textlength(s, font=font)  # type: ignore
    except Exception:
        measure = lambda s: len(s) * 6
    def _fit_text(text: str, max_width: int) -> str:
        if measure(text) <= max_width:
            return text
        suffix = "..."
        trimmed = text
        while trimmed and measure(trimmed + suffix) > max_width:
            trimmed = trimmed[:-1]
        return trimmed + suffix if trimmed else text
    max_items = 20
    all_interfaces = [str(x).strip() for x in interfaces if str(x).strip()]
    all_internals = [str(x).strip() for x in internals if str(x).strip()]
    overflow_if = len(all_interfaces) - max_items if len(all_interfaces) > max_items else 0
    overflow_in = len(all_internals) - max_items if len(all_internals) > max_items else 0
    interfaces = all_interfaces[:max_items]
    internals = all_internals[:max_items]
    if overflow_if > 0:
        interfaces.append(f"... +{overflow_if} more")
    if overflow_in > 0:
        internals.append(f"... +{overflow_in} more")
    lane_rows = max(len(interfaces), len(internals), 1)
    lane_step = 48 if lane_rows <= 10 else (36 if lane_rows <= 15 else 28)
    lane_y0 = 220
    needed_h = lane_y0 + lane_rows * lane_step + 80
    if needed_h > height:
        height = needed_h
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)

    def _rounded(box, fill="#FFFFFF", outline="black", radius=8, w=1):
        draw.rounded_rectangle(box, radius=radius, outline=outline, width=w, fill=fill)

    header_box = (40, 24, width - 40, 96)
    _rounded(header_box, fill="#DDE8D6", radius=10, w=2)
    module_text = _fit_text(module_label or "Unit Structure", header_box[2] - header_box[0] - 20)
    draw.text((header_box[0] + 12, header_box[1] + 20), module_text, fill="black", font=font)
    draw.text(
        (header_box[0] + 12, header_box[1] + 46),
        f"Interfaces: {len(all_interfaces)} | Internals: {len(all_internals)}",
        fill="black",
        font=font,
    )

    left_x = 90
    center_x = width // 2
    right_x = width - 510
    lane_w = 420
    lane_h = 34

    # Lane titles
    draw.text((left_x, lane_y0 - 32), "Interface Functions", fill="black", font=font)
    draw.text((right_x, lane_y0 - 32), "Internal Functions", fill="black", font=font)

    # Core node
    core_box = (center_x - 170, 134, center_x + 170, 186)
    _rounded(core_box, fill="#FFF3CD", radius=10, w=2)
    draw.text((core_box[0] + 12, core_box[1] + 18), _fit_text(module_label or "Core Module", 320), fill="black", font=font)

    def _arrow(p1, p2):
        draw.line([p1, p2], fill="black", width=1)
        x2, y2 = p2
        draw.polygon([(x2, y2), (x2 - 7, y2 - 4), (x2 - 7, y2 + 4)], fill="black")

    # Render interface lane
    if not interfaces:
        interfaces = ["N/A"]
    for idx, name in enumerate(interfaces):
        y = lane_y0 + idx * lane_step
        box = (left_x, y, left_x + lane_w, y + lane_h)
        _rounded(box, fill="#CFE2FF", radius=6)
        draw.text((left_x + 8, y + 8), _fit_text(name, lane_w - 16), fill="black", font=font)
        _arrow((core_box[0], (core_box[1] + core_box[3]) // 2), (left_x + lane_w, y + lane_h // 2))

    # Render internal lane
    if not internals:
        internals = ["N/A"]
    for idx, name in enumerate(internals):
        y = lane_y0 + idx * lane_step
        box = (right_x, y, right_x + lane_w, y + lane_h)
        _rounded(box, fill="#D9F2D9", radius=6)
        draw.text((right_x + 8, y + 8), _fit_text(name, lane_w - 16), fill="black", font=font)
        _arrow((core_box[2], (core_box[1] + core_box[3]) // 2), (right_x, y + lane_h // 2))

    img.save(str(out_path))
    return str(out_path)


def _render_swcom_overview_image(swcoms: List[str], out_path: Path) -> Optional[str]:
    if not swcoms:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    width = 900
    box_h = 28
    margin = 20
    max_items = min(len(swcoms), 20)
    height = margin * 2 + max_items * (box_h + 10) + 40
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 12)
        except Exception:
            font = ImageFont.load_default()
    title = "Software Unit Structure Overview"
    draw.text((margin, margin), title, fill="black", font=font)
    y = margin + 24
    for name in swcoms[:max_items]:
        draw.rectangle([margin, y, width - margin, y + box_h], outline="black", width=1)
        draw.text((margin + 8, y + 6), name, fill="black", font=font)
        y += box_h + 10
    img.save(str(out_path))
    return str(out_path)


# ── 정본에만 있는 남의 함수 heading 을 어떻게 할 것인가 ──────────────────────
#
# 정본을 템플릿으로 쓰면 heading 이 그 문서 전체(실측 KJPDS02 정본 1,035개)만큼 오는데
# 이번 분석의 payload 는 그 부분집합이다(실측 57개). 나머지는 빈 `[ Function Information ]`
# 서식으로 남는다 — 문서 행의 23%. 그게 옳은지는 **사람이 정한다**:
#
#   · 남기면(`keep`) 무엇이 분석되지 않았는지 문서에 드러난다.
#   · 지우면(`drop`) 분석한 함수만 담긴 문서가 된다 — 정본을 부분집합으로 쓰는 경우.
#
# 기본은 `keep`(= 종전 동작)이라 **고르기 전까지 산출물은 바뀌지 않는다**.
UNMATCHED_HEADINGS_KEEP = "keep"
UNMATCHED_HEADINGS_DROP = "drop"
UNMATCHED_HEADINGS_CHOICES = (UNMATCHED_HEADINGS_KEEP, UNMATCHED_HEADINGS_DROP)

# 함수 절의 heading 인가. ⚠ **한 곳에만** 둔다 — 세는 쪽과 지우는 쪽이 각자 리터럴을
# 들고 있으면 `\b` 하나 빠진 것만으로 두 집합이 갈린다(이 라운드에서 실제로 겪었다).
_SWUFN_HEADING_RE = re.compile(r"\bswufn_\d+\b", re.I)


def normalize_unmatched_headings(value: Any) -> "Tuple[str, str]":
    """``(정규화된 값, 알 수 없었던 원본 or "")``.

    ⚠ 모르는 값은 **안 지우는 쪽**(`keep`)으로 떨어진다. 반대로 두면 오타 하나에
      문서가 조용히 얇아지고, 그건 되돌릴 수 없는 방향의 실수다.
      `generators.suts.normalize_scope` 와 **같은 계약**이다 — 게이트가 이 함수를
      import 해서 쓰므로 규칙이 두 곳에 갈리지 않는다.
    """
    raw = str(value or "").strip()
    low = raw.lower()
    if not low:
        return UNMATCHED_HEADINGS_KEEP, ""
    if low in UNMATCHED_HEADINGS_CHOICES:
        return low, ""
    return UNMATCHED_HEADINGS_KEEP, raw


def _distinct_cells(row) -> List[Any]:
    """`row.cells` 에서 같은 `<w:tc>` 를 **한 번만** 낸다(첫 등장 순).

    (R53 N27-c) python-docx 는 병합 칸을 gridSpan 만큼 같은 `_Cell` 로 반복해 낸다 — 6열 라벨|값 행이면 6개 중 다른 칸은 2개뿐인데
    `c.text` 는 부를 때마다 run 마다 xpath 를 돌린다(라이브: 이 읽기가 로직 이미지 행 찾기·행 종류 되짚기·머리글 판정에서 표당
    수십 회). 판정이 `any(...)`/집합/첫 칸이거나 쓰기가 같은 값의 멱등 대입인 자리에서만 쓴다 — 그런 자리는 중복 칸이 결과를
    바꾸지 않는다. 세로 병합 이어짐 칸도 위 칸의 `_tc` 를 내므로 같은 규칙으로 접힌다.
    """
    out: List[Any] = []
    seen: Set[int] = set()
    for c in row.cells:
        key = id(c._tc)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _grid_cells(table) -> List[Any]:
    """표의 그리드 셀 목록을 **한 번만** 만든다 — 그 시점의 `table.cell(r, c)` 와 같은 `_Cell` 객체다.

    (R47-j N27-b) python-docx 의 `Table.cell(r, c)` 는 `self._cells[c + r * col_count]` 인데 `_cells` 가 **프로퍼티**라
    부를 때마다 표 전체 `<w:tc>` 를 훑어 셀 객체를 새로 만든다(1.2.0 실측). 셀마다 한 번씩 부르면 셀 수의 제곱이다 —
    라이브 프로파일(kjpds02_pv · 1,157함수 · DOCX 단계 1,486초 단독): 이 API 아래가 DOCX 시간의 **55%**
    (`_add_blank_table` 38.6% · `_merge_function_info_table` 12.7% · 로직 이미지 삽입 경로 일부).
    `_fill_function_info_table` 은 같은 함정을 이미 고쳐 두었는데(docstring 의 81,510회 프로파일) 형제 셋은 그대로였다 —
    이 저장소 단골인 "쌍둥이 한쪽만 수정".

    스냅샷 `[c + r * col_count]` 는 gridSpan 반복·vMerge 위 셀 참조까지 `_cells` 와 같은 규칙으로 만들어진 **같은 목록**이다.
    ⚠ 병합은 표 모양을 바꾸므로 스냅샷은 **병합 전에 집은 같은 행의 셀**에만 유효하다 — 가로 병합은 그 행의 `<w:tc>` 만
    지우고 다른 행의 요소는 살아 있으니 행 단위로 쓰면 된다(`_merge_function_info_table` 의 사용 방식).
    ⚠ (R47-j 리뷰 W1) 위 단언은 **직사각 표**(모든 행의 gridSpan 합 == `tblGrid` 열 수, gridBefore/After 없음) 전제다.
      행 폭이 다른(ragged) 표에선 평면 인덱스가 다른 행의 셀을 집어 가로 병합이 **세로 병합을 만들고**, vMerge 는 `_cells`
      의 개수가 아니라 엔트리를 바꿔 스냅샷이 그 순간 낡는다. 병합하는 호출자는 `_is_uniform_grid` 로 먼저 가른다.
    """
    return list(table._cells)


def _is_uniform_grid(table, stride: int) -> bool:
    """모든 행이 `tblGrid` 폭을 정확히 채우는가(gridBefore/After 없음) — 스냅샷 병합이 옛 `table.cell()` 경로와 같아지는 조건."""
    try:
        for tr in table._tbl.tr_lst:
            if int(getattr(tr, "grid_before", 0) or 0) or int(getattr(tr, "grid_after", 0) or 0):
                return False
            if sum(int(tc.grid_span) for tc in tr.tc_lst) != stride:
                return False
        return True
    except Exception:  # noqa: BLE001 — 판단 불가면 느린(안전한) 경로
        return False


# ── (R53 N27-c) 그림 삽입 싱크 · 같은 행 가로 병합 빠른 경로 ─────────────────────────────────────

class _PictureSink:
    """한 문서 생성 동안의 그림 삽입 — python-docx `Run.add_picture` 와 **같은 XML·같은 파트·같은 rId·같은 id** 를 내되
    그림마다 문서 크기에 비례해 돌던 두 비용을 걷어낸다.

    (R53 N27-c) python-docx 1.2.0 `Run.add_picture` 는 그림 한 장마다:
      ① `ImageParts._get_by_sha1` — 기존 이미지 파트 **전부**의 blob 을 다시 sha1 한다(`ImagePart.sha1` 은 캐시가 없다).
         정본 템플릿 + 함수 1,157장이면 파트 해시가 수백만 번이다.
      ② `StoryPart.next_id` — 문서 전체에 `//@id` xpath 를 돌려 "숫자 id 최대값 + 1" 을 잡는다(14MB document.xml).
    라이브 프로파일(R47-j 수정 후 572초)에서 `add_picture` 아래가 26.3%(`next_id` 14.8% · `sha1` 7%) 였다.

    등가 근거(1.2.0 소스 — 같은 API 를 같은 순서로 부른다):
      `Run.add_picture(path, w, h)` = `part.new_pic_inline` → `get_or_add_image`(`package.image_parts.get_or_add_image_part`
      뒤 `relate_to(part, RT.IMAGE)`) → `image_part.image.scaled_dimensions(w, h)` → `next_id` → `CT_Inline.new_pic_inline`
      → `run._r.add_drawing(inline)`.
      · sha1 색인: `_get_by_sha1` 는 `_image_parts` **목록 순서**로 첫 일치를 돌려준다 → 목록 순서대로 `setdefault` 하면 같은
        파트다. 다른 경로(`Document.add_picture` 등)가 목록에 파트를 붙였을 수 있으니 조회 전마다 **꼬리만** 마저 색인한다.
      · 파일명·크기는 원판처럼 **매칭된 파트의** `image` 에서 읽는다(중복이면 기존 파트의 이름이 docPr/cNvPr 에 실린다).
      · id: `next_id` = "문서 안 숫자 `@id` 최대값 + 1". 본문은 `_clear_docx_body` 뒤로 **자라기만** 하므로 최대값은 우리가 넣는
        그림(docPr id = 배정값 · cNvPr id = 0)과 원본 블록 되붙임(`note_appended`)으로만 오른다. 첫 배정 때 원판과 같은 xpath 로
        한 번 재고 그 뒤로는 추적한다. 다른 경로가 그림을 넣을 수 있는 자리에선 `invalidate()` — 추적이 틀릴 수 있는 순간엔
        항상 원판의 계산으로 돌아간다.
    ⚠ `image_parts._image_parts`·`PackURI.idx`·`ImagePart.from_image` 는 비공개/내부 API(1.2.0 고정 — R47-j I4 와 같은 축).
    """

    def __init__(self, doc) -> None:
        self._doc = doc
        self._part = doc.part
        self._package = self._part.package
        self._by_sha1: Dict[str, Any] = {}
        self._indexed = 0
        self._used_idx: Set[Any] = set()     # 파트 이름 번호(`partname.idx`) — 원판 `_next_image_partname` 의 used_numbers
        self._next_free = 1                   # 최소 빈 번호 커서 — 번호는 늘기만 하므로 단조
        self._max_id: Optional[int] = None
        self.pictures = 0            # 계측용 — 이 싱크로 넣은 그림 수
        self.full_id_scans = 0       # 계측용 — `//@id` 전체 스캔 횟수(첫 배정 + invalidate 뒤)

    def _parts(self) -> List[Any]:
        return self._package.image_parts._image_parts      # `_get_by_sha1` 가 도는 바로 그 목록·그 순서

    def _index_tail(self) -> None:
        parts = self._parts()
        for part in parts[self._indexed:]:
            self._by_sha1.setdefault(part.sha1, part)     # 같은 해시가 둘이면 원판처럼 **앞의 것**
            self._used_idx.add(part.partname.idx)
        self._indexed = len(parts)

    def _new_part(self, image):
        """`ImageParts._add_image_part` 와 같은 파트(같은 이름) — 원판은 그림마다 파트 전부를 훑어 "빈 번호 중 최소" 를 찾는다
        (`_next_image_partname`, 파트 수 제곱). 번호는 늘기만 하므로 최소 빈 번호는 단조 — 커서 하나로 같은 번호를 낸다."""
        from docx.opc.packuri import PackURI  # type: ignore
        from docx.parts.image import ImagePart  # type: ignore

        n = self._next_free
        while n in self._used_idx:
            n += 1
        self._next_free = n
        part = ImagePart.from_image(image, PackURI("/word/media/image%d.%s" % (n, image.ext)))
        self._package.image_parts.append(part)
        self._used_idx.add(n)
        return part

    def invalidate(self) -> None:
        """다른 경로가 숫자 `@id` 를 가진 요소를 넣었을 수 있다 — 다음 배정은 원판처럼 문서 전체를 다시 잰다."""
        self._max_id = None

    def note_appended(self, el) -> None:
        """원본 블록(표지 sdt·보존 표)을 되붙인 뒤 부른다 — 그 안의 숫자 `@id` 가 최대값을 올릴 수 있다."""
        if self._max_id is None:
            return
        for raw in el.xpath(".//@id"):
            text = str(raw)
            if text.isdigit():
                self._max_id = max(self._max_id, int(text))

    def _alloc_id(self) -> int:
        if self._max_id is None:
            used = [int(str(s)) for s in self._part._element.xpath("//@id") if str(s).isdigit()]   # 원판 `next_id` 그대로
            self._max_id = max(used) if used else 0
            self.full_id_scans += 1
        return self._max_id + 1

    def add_picture(self, run, image_path: str, width=None, height=None):
        """`run.add_picture(image_path, width, height)` 와 같은 결과."""
        from docx.image.image import Image  # type: ignore
        from docx.opc.constants import RELATIONSHIP_TYPE as RT  # type: ignore
        from docx.oxml.shape import CT_Inline  # type: ignore
        from docx.shape import InlineShape  # type: ignore

        image = Image.from_file(image_path)               # 원판과 같은 순서 — 파일 오류는 여기서 나고 문서는 그대로다
        self._index_tail()
        sha1 = image.sha1
        part = self._by_sha1.get(sha1)
        if part is None:
            part = self._new_part(image)
            self._by_sha1[sha1] = part
            self._indexed = len(self._parts())
        rId = self._part.relate_to(part, RT.IMAGE)
        part_image = part.image                           # 중복이면 **기존 파트**의 이름·크기(원판과 같다)
        cx, cy = part_image.scaled_dimensions(width, height)
        shape_id = self._alloc_id()
        inline = CT_Inline.new_pic_inline(shape_id, rId, part_image.filename, cx, cy)
        run._r.add_drawing(inline)
        self._max_id = shape_id                           # 방금 넣은 docPr id 가 새 최대값(cNvPr id 는 0)
        self.pictures += 1
        return InlineShape(inline)

    def add_picture_paragraph(self, image_path: str, width=None, height=None):
        """`Document.add_picture(image_path, width, height)` 와 같다 — 새 문단의 새 run 에 넣는다."""
        run = self._doc.add_paragraph().add_run()
        return self.add_picture(run, image_path, width, height)


def _hmerge_fast(tc_a, tc_b) -> bool:
    """같은 행 안의 가로 병합을 python-docx `CT_Tc.merge` 와 **같은 XML** 로, 항법 xpath 없이 수행한다.

    전제가 하나라도 어긋나면 아무것도 바꾸지 않고 False — 호출자는 원판 `merge` 로 간다(원판이 던질 예외도 그쪽에서 그대로).

    (R53 N27-c) 원판은 병합 한 번에 `_tbl`·`_tr`·`preceding-sibling`·`following-sibling` xpath 를 셀마다 다시 돌린다 —
    함수 정보 표 1,157개 × 행마다 1~2회 병합이면 xpath 수백만 번이고, 라이브 프로파일에서 `merge` 아래가 24.7% 였다.

    등가 근거(1.2.0 `CT_Tc.merge`): 두 tc 가 같은 `w:tr` 의 직속 자식이고 둘 다 vMerge 가 없으면 `_span_dimensions` 는
    (top=행, left=a.grid_offset, height=1, width=b.right−a.left) 이고 `top_tc` 는 a 자신이다. `_grow_to(width, 1)` 는
    `_span_to_width(width, a, None)`: `a._move_content_to(a)` 는 no-op, `grid_span < width` 인 동안 `_swallow_next_tc` —
    다음 tc 가 **비어 있으면** `_move_content_to` 도 no-op 이라 `_add_width_of` · `grid_span +=` · `_remove()` 만 남는다.
    셀은 행을 빈틈없이 덮으므로 삼키는 tc 는 정확히 a 다음부터 b 까지다. 끝으로 `vMerge = None`. 여기서는 항법만 걷어내고
    **변이는 원판과 같은 setter 를 같은 순서로** 부른다. 삼킬 셀에 내용이 있으면(원판은 옮긴다) 원판에 맡긴다.
    예외까지 등가인 범위는 행이 `w:tbl` **직속**일 때다 — `w:sdt` 로 감싼 행은 원판이 ValueError 를 던지므로 그쪽으로 보낸다(리뷰 W2).
    """
    from docx.oxml.ns import qn  # type: ignore

    tr = tc_a.getparent()
    if tr is None or tr is not tc_b.getparent() or tr.tag != qn("w:tr"):
        return False
    tbl = tr.getparent()
    if tbl is None or tbl.tag != qn("w:tbl"):                  # (리뷰 W2) `w:sdt` 로 감싼 행 — 원판은 `tr_lst.index` 에서 ValueError 를 던진다 → 원판에
        return False
    if tc_a.vMerge is not None or tc_b.vMerge is not None:      # top/bottom 이 행 밖으로 나간다 → 원판에
        return False
    tcs = tr.tc_lst
    a_i = b_i = -1
    for i, tc in enumerate(tcs):
        if tc is tc_a:
            a_i = i
        if tc is tc_b:
            b_i = i
    if a_i < 0 or b_i < 0 or a_i > b_i:                          # b 가 왼쪽이면 원판이 b 를 키운다 → 원판에
        return False
    swallow = tcs[a_i + 1:b_i + 1]
    for tc in swallow:
        if not tc._is_empty:
            return False
    for tc in swallow:                                           # `_swallow_next_tc` 와 같은 순서·같은 setter
        tc_a._add_width_of(tc)
        tc_a.grid_span += tc.grid_span
        tr.remove(tc)
    tc_a.vMerge = None                                           # `_span_to_width` 마지막 줄(높이 1 → None)
    return True


def _merge_cells(cell_a, cell_b) -> None:
    """`cell_a.merge(cell_b)` — 같은 행의 빈 셀 가로 병합이면 빠른 경로, 아니면 python-docx 원판(예외도 원판 것)."""
    if not _hmerge_fast(cell_a._tc, cell_b._tc):
        cell_a.merge(cell_b)


def _merge_function_info_table(table, cols: int, layout=None) -> None:
    """함수 정보 표의 셀을 행 종류에 맞게 병합한다.

    `layout` 이 있으면 행마다 종류(`full`/`pair`/`grid`)를 보고 병합한다. 없으면
    P2-3 이전과 같은 균일 병합(행0 전체 + 나머지 라벨/값)이라, 문서에서 읽어 온
    표를 다시 정규화하는 경로는 그대로 동작한다.

    ⚠ **`grid` 행은 병합하지 않는다.** 정본의 `No|Name|Type|Value Range|Reset
    Value|Description` 은 6칸이 각각 독립이고, 여길 라벨/값으로 병합하면 파라미터가
    통째로 사라진다. 표가 6열보다 넓으면(실측 템플릿 415개 중 124개가 7열) 남는
    꼬리만 마지막 칸에 합쳐 정본과 같은 6칸으로 보이게 한다.
    """
    if not table or cols < 4:
        return
    try:
        kinds = [str(k) for k, _ in (layout or [])]
        n_rows = len(table.rows)
        # 표당 그리드 1회 — 행 안의 두 병합은 서로 다른 `<w:tc>` 를 건드리고, 다른 행의 요소는 살아 있다(`_grid_cells`).
        #   (R53 N27-c) 병합 자체는 `_merge_cells` — 같은 행의 빈 셀이면 xpath 없는 빠른 경로, 아니면 python-docx 원판.
        #   단 **직사각 표**에서만이다(리뷰 W1) — 행 폭이 다른 표는 옛 경로대로 호출마다 재계산한다(느리지만 같은 결과).
        stride = table._column_count
        if _is_uniform_grid(table, stride):
            grid = _grid_cells(table)

            def _c(r: int, c: int):
                return grid[c + r * stride]
        else:
            _logger.warning("함수 정보 표의 행 폭이 tblGrid(%d열)와 달라 셀 접근을 호출마다 재계산한다(느린 경로)", stride)

            def _c(r: int, c: int):
                return table.cell(r, c)

        for r_idx in range(n_rows):
            if r_idx < len(kinds):
                kind = kinds[r_idx]
            else:
                kind = FN_ROW_FULL if r_idx == 0 else FN_ROW_PAIR
            if kind == FN_ROW_GRID:
                if cols > PARAM_GRID_COLS:
                    _merge_cells(_c(r_idx, PARAM_GRID_COLS - 1), _c(r_idx, cols - 1))
                continue
            if kind == FN_ROW_FULL:
                _merge_cells(_c(r_idx, 0), _c(r_idx, cols - 1))
                continue
            if cols >= 2:
                _merge_cells(_c(r_idx, 0), _c(r_idx, 1))
            if cols >= 4:
                _merge_cells(_c(r_idx, 2), _c(r_idx, cols - 1))
    except Exception as exc:  # noqa: BLE001 — 병합 실패가 문서 생성을 막아선 안 된다
        # (R47-j 리뷰 I5/X8) 예전엔 여기가 완전 침묵이라 "일부 행만 병합된 표" 와 정상을 산출물에서 구분할 수 없었다.
        _logger.warning("함수 정보 표 병합 중단(%s: %s) — 남은 행은 병합되지 않은 채 남는다", type(exc).__name__, str(exc)[:120])


def _infer_function_info_layout(table):
    """이미 만들어진 표에서 행 종류를 되짚는다 — 문서 후처리 정규화용.

    ⚠ 왜 필요한가: `_normalize_function_info_tables` 는 완성된 문서를 훑어 표를 다시
    병합하는데, P2-3 이 넣은 파라미터 그리드는 병합 대상이 **아니다**. 종류를 모르고
    균일 병합하면 방금 쓴 파라미터 행이 라벨/값 두 칸으로 접혀 통째로 사라진다.

    ⚠ **셀 개수로 판정하면 안 된다.** 처음엔 "칸이 3개 이상이면 그리드" 로 썼는데,
    아직 한 번도 병합되지 않은 라벨/값 표도 6칸이라 **정규화가 통째로 죽었다**
    (음성 대조군이 잡았다). 그래서 정본 배치의 **내용**으로 판정한다 —
    `report_gen.requirements._extract_function_info_from_docx` 가 같은 문서를 되읽을 때
    쓰는 것과 같은 상태기계다(섹션 머리 → 그리드 헤더 → 번호로 시작하는 데이터 행).
    (R54 N49) `[ Logic Diagram ]` 머리행과 그 다음 그림행은 full — 그림행은 글이 없어 내용이 아니라 **머리행 뒤라는 위치**로 판정한다.
    """
    layout = []
    try:
        in_params = False
        logic_body_next = False
        for r_idx, row in enumerate(list(table.rows)):
            cells = [str(c.text or "").strip() for c in _distinct_cells(row)]   # (R53) 판정은 첫 칸·집합·any 뿐 — 중복 칸 불필요
            first = cells[0] if cells else ""
            norm = re.sub(r"[\[\]\s]+", " ", first).strip().lower()
            if r_idx == 0:
                layout.append((FN_ROW_FULL, []))
                continue
            if logic_body_next:
                logic_body_next = False
                if len(cells) == 1 or all(not c for c in cells):     # (R54 N49) 머리행 다음 = 전폭 그림행 — 전폭 한 칸이거나 전부 빈 칸일 때만(리뷰 W2)
                    layout.append((FN_ROW_FULL, []))
                    continue
                # 모양이 다르면(라벨|값 행이 바로 온 표) 보통 행으로 — 아래 판정으로 흘린다
            if is_logic_diagram_label(first) and (is_logic_diagram_header(first) or len(cells) == 1):
                # (R54 N49) 정본 배치의 머리행(대괄호 표기, 또는 이미 전폭 한 칸). 옛 라벨|값 한 행(대괄호 없음·두 칸)은 아래 pair 로.
                in_params = False
                logic_body_next = True
                layout.append((FN_ROW_FULL, []))
                continue
            if norm in ("input parameters", "output parameters", "input paramters"):
                in_params = True
                layout.append((FN_ROW_FULL, []))
                continue
            if in_params:
                lowered = {c.lower() for c in cells}
                if "no" in lowered and ("name" in lowered or "type" in lowered):
                    layout.append((FN_ROW_GRID, []))
                    continue
                if first[:1].isdigit():
                    layout.append((FN_ROW_GRID, []))
                    continue
                in_params = False
            layout.append((FN_ROW_PAIR, []))
    except Exception as exc:   # noqa: BLE001 - 되짚기 실패가 문서 생성을 막아선 안 된다
        _logger.warning("함수 정보 표 행 종류 추론 실패(%s) — 균일 병합으로 되돌린다: %s",
                        type(exc).__name__, exc)
        return None
    return layout


def _normalize_function_info_tables(doc) -> None:
    if not doc:
        return
    try:
        for table in doc.tables:
            if not table.rows:
                continue
            _row0 = table.rows[0]                                    # (R53) `rows[0]` 은 부를 때마다 전 행을 다시 만든다 — 한 번만
            header_cells = [c.text.strip() for c in _distinct_cells(_row0)]
            if not any("Function Information" in c for c in header_cells):
                continue
            cols = len(table.columns)
            for cell in _distinct_cells(_row0):
                cell.text = "[ Function Information ]"             # 같은 칸에 같은 값 — 멱등이라 한 번이면 같다
            _merge_function_info_table(table, cols, _infer_function_info_layout(table))
    except Exception:
        pass


def _fill_function_info_table(table, layout) -> None:
    """함수 정보 표를 채운다.

    ⚠ **`table.cell(r, c)` 를 쓰지 말 것.** python-docx 의 그 API 는 호출할 때마다
    그리드를 처음부터 훑는다. 예전 구현은 바로 윗줄에서 `table.rows[r].cells` 로 행을
    이미 해석해 놓고 다음 줄에서 `table.cell(r, 0)` 으로 되돌아가, 행 수에 대해 축이
    하나 더 붙었다(프로파일: `table.cell()` 81,510회 → `get_child_element` 4,390만 회).
    `table.rows[r]` 도 마찬가지다 — `_Rows.__getitem__` 은 구현이 `list(self)[idx]` 라
    **인덱싱할 때마다 전 행을 새로 materialize** 한다(`rows` 자체는 lazyproperty 라
    캐시되지만 그건 도움이 안 된다). 그래서 `list(table.rows)` 로 한 번만 펼친다.

    ⚠ **병합 셀이 있어도 등가다** — 이 표는 `_merge_function_info_table` 로 행0 전체와
    행1+ 의 `[0-1]`·`[2..cols-1]` 이 병합돼 있다. 실측(19행 6열, 실제 병합 모양 재현):
    114칸 전부 `table.cell(r,c)._tc is table.rows[r].cells[c]._tc`, 결과 XML 바이트
    동일, 소요 **1,918ms → 791ms (2.42배)**.
    """
    if not table or not layout:
        return
    try:
        trows = list(table.rows)          # `table.rows` 재해석 방지
        for r_idx, (kind, cells_text) in enumerate(layout):
            if r_idx >= len(trows):
                break
            cells = trows[r_idx].cells    # 행당 한 번만 해석
            # (R53 N27-c) 같은 `<w:tc>` 에 여러 번 쓰지 않는다 — python-docx 는 병합 칸을 gridSpan 만큼 반복해 내므로 "전부 비우고
            #   다시 쓰기" 가 라벨|값 행에서 setter 8회, 머리글 행에서 12회였다(칸은 2개·1개). 대입은 마지막 값이 이기고 setter 는
            #   멱등이라, 예전과 같은 순서로 **계획**만 세운 뒤 칸마다 한 번 쓴다(XML 동일 — `test_docx_function_info_fill` 이 옛 구현과 대조).
            plan: Dict[int, Tuple[Any, str]] = {}

            def _put(c, text: str) -> None:
                plan[id(c._tc)] = (c, text)

            for c in cells:
                _put(c, "")
            if kind == FN_ROW_GRID:
                for c_idx, val in enumerate(cells_text[:len(cells)]):
                    _put(cells[c_idx], str(val))
                for c, text in plan.values():
                    c.text = text
                continue
            if kind == FN_ROW_FULL:
                head = str(cells_text[0]) if cells_text else ""
                for c in cells:
                    _put(c, head)
                for c, text in plan.values():
                    c.text = text
                continue
            # ⚠ 값 칸 선택은 P2-3 이전과 **글자 그대로 같게** 둔다. 좁은 표(6열 미만)는
            #   라벨/값 쌍을 한 행에 여러 개 접어 넣으므로(`_pack_pairs_into_rows`)
            #   `cells_text[-1]` 을 쓰면 첫 쌍의 라벨에 마지막 쌍의 값이 붙는다.
            label = str(cells_text[0]) if len(cells_text) > 0 else ""
            if len(cells_text) > 2:
                value = str(cells_text[2])
            elif len(cells_text) > 1:
                value = str(cells_text[1])
            else:
                value = ""
            if len(cells) > 0:
                _put(cells[0], label)
            if len(cells) > 2:
                _put(cells[2], value)
            for c, text in plan.values():
                c.text = text
    except Exception as exc:   # noqa: BLE001 - 표 채우기 실패가 문서 생성을 막아선 안 된다
        # 예전엔 `pass` 라 표가 통째로 비어도 흔적이 없었다.
        _logger.warning("함수 정보 표 채우기 실패(%s) — 그 표는 빈 채로 남는다: %s",
                        type(exc).__name__, exc)


def _insert_logic_image_in_table(table, cols: int, logic_img: str, picture_sink=None) -> bool:
    """함수 정보 표의 Logic Diagram 그림 칸에 그림을 넣는다.

    그림 칸은 배치에 따라 둘 중 하나다(R54 N49):
    · 정본 배치 — `[ Logic Diagram ]` 전폭 머리행(대괄호 표기, 또는 이미 전폭 한 칸) 다음의 **전폭 그림행**(KJPDS02 정본 989/989).
    · 옛 배치 — `Logic Diagram` 라벨|값 한 행의 값 칸(`min(2, cols-1)` 열). 좁은 표(6열 미만) 폴백은 아직 이 배치다.
    머리행 뒤에 행이 없으면 False(호출부가 표 뒤 문단으로 폴백한다) — 조용히 머리행에 덮어쓰지 않는다.

    `picture_sink`(`_PictureSink`)가 있으면 그 싱크로 넣는다(R53 N27-c — 결과 XML 은 `run.add_picture` 와 같고 그림마다
    문서 전체를 훑지 않는다). 없으면 python-docx 원판.
    """
    if not table or not logic_img:
        return False
    try:
        from docx.shared import Inches  # type: ignore
    except Exception:
        Inches = None  # type: ignore
    def _clear_cell(cell) -> None:
        """값 칸의 **내용만** 비운다 — `w:tcPr`(gridSpan·tcW)는 남긴다.

        (R53 N48) 예전엔 `tc` 의 자식을 **전부** 지워 셀 속성까지 사라졌다. 이 칸은 `_merge_function_info_table` 이 `cols-2` 열로
        병합한 값 칸이라 gridSpan 이 사라지면 그 행만 좁은 칸이 되고(ragged), ① Word 에서 Logic Diagram 행이 다른 행과 폭이 다르며
        ② 정규화가 그 표를 비직사각으로 판정해 표마다 느린 경로(셀마다 그리드 재구성 — 셀 수의 제곱) + IndexError 경고를 냈다 — 라이브 실측
        989/989 표(Initial commit 이래). python-docx `_Cell.text` setter 와 같은 규약(`clear_content` = tcPr 만 남김)으로 비운다.
        """
        try:
            tc = cell._tc
            tc.clear_content()            # `w:tcPr` 를 제외한 자식 제거(python-docx)
            tc.add_p()
        except Exception as e:
            _logger.debug("Cell XML clear failed: %s", e)
            try:
                cell.text = ""
            except Exception:
                pass
    try:
        stride = table._column_count
        grid = _grid_cells(table)             # 표당 1회 — `Table.cell` 은 호출마다 그리드를 다시 만든다
        rows_l = list(table.rows)
        for r_idx, row in enumerate(rows_l):
            cells = [c.text.strip() for c in _distinct_cells(row)]     # (R53) 병합 칸은 한 번만 읽는다 — any() 판정은 같다
            hit = next((c for c in cells if is_logic_diagram_label(c)), None)
            if hit is not None:
                if is_logic_diagram_header(hit) or len(cells) == 1:
                    # (R54 N49) 정본 배치 — 그림은 다음 전폭 행. 머리행이 한 칸뿐이면 "값 칸" 이 곧 라벨 칸이라 거기 넣으면 라벨이 지워진다.
                    #   다음 행은 **행 단위**로 잡고(그리드 평면 인덱스는 비직사각 표에서 어긋난다 — 리뷰 W3) 전폭 한 칸이거나 전부 빈 칸일
                    #   때만 지운다 — 라벨|값 행이 바로 오면 그 라벨을 지우는 대신 False(표 뒤 문단 폴백 — 검증기는 그 표를 '그림 없음' 으로 센다).
                    if r_idx + 1 >= len(rows_l):
                        _logger.warning("Logic Diagram 머리행 뒤에 그림행이 없다 — 표 뒤 문단으로 폴백한다")
                        return False
                    nxt = _distinct_cells(rows_l[r_idx + 1])
                    if not nxt or not (len(nxt) == 1 or all(not c.text.strip() for c in nxt)):
                        _logger.warning("Logic Diagram 머리행 다음 행이 그림행 모양(전폭 한 칸·빈 칸)이 아니다 — 표 뒤 문단으로 폴백한다")
                        return False
                    target_cell = nxt[0]
                else:
                    target_cell = grid[min(2, cols - 1) + r_idx * stride]      # 옛 배치(라벨|값 한 행) — 좁은 표 폴백이 아직 쓴다
                _clear_cell(target_cell)
                p = target_cell.paragraphs[0] if target_cell.paragraphs else target_cell.add_paragraph()
                run = p.add_run()
                _width = Inches(5.2) if Inches else None
                if picture_sink is not None:
                    picture_sink.add_picture(run, str(logic_img), width=_width)
                else:
                    run.add_picture(str(logic_img), width=_width)
                return True
    except Exception as e:
        _logger.warning("Failed to insert logic image in table: %s", e)
        return False
    return False


def _clear_docx_body(doc) -> None:
    try:
        body = doc._body._element  # type: ignore[attr-defined]
        for child in list(body):
            tag = getattr(child, "tag", "")
            if isinstance(tag, str) and tag.endswith("}sectPr"):
                continue
            body.remove(child)
    except Exception:
        pass


def _remove_docx_paragraphs(doc, texts: List[str]) -> None:
    try:
        from docx.text.paragraph import Paragraph  # type: ignore
    except Exception:
        return
    targets = {t.strip() for t in texts if t and t.strip()}
    if not targets:
        return
    try:
        body = doc._body._element  # type: ignore[attr-defined]
        for child in list(body):
            tag = getattr(child, "tag", "")
            if not isinstance(tag, str) or not tag.endswith("}p"):
                continue
            para = Paragraph(child, doc)
            if (para.text or "").strip() in targets:
                body.remove(child)
    except Exception:
        pass
    try:
        for table in doc.tables:
            header_cells = [c.text.strip() for c in table.rows[0].cells] if table.rows else []
            is_function_info = any("Function Information" in c for c in header_cells)
            for row in table.rows:
                for cell in row.cells:
                    if not is_function_info and (cell.text or "").strip() in targets:
                        cell.text = ""
                    for paragraph in cell.paragraphs:
                        if not is_function_info and (paragraph.text or "").strip() in targets:
                            paragraph.text = ""
    except Exception:
        pass


def _template_has_placeholders(doc) -> bool:
    def _check_text(t: str) -> bool:
        return bool(t and "{{" in t and "}}" in t)

    try:
        for p in doc.paragraphs:
            if _check_text(p.text or ""):
                return True
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        if _check_text(p.text or ""):
                            return True
        for section in doc.sections:
            for hf in [section.header, section.footer]:
                if not hf or not hasattr(hf, "paragraphs"):
                    continue
                for p in hf.paragraphs:
                    if _check_text(p.text or ""):
                        return True
    except Exception:
        return False
    return False


def _para_text(p_el) -> str:
    """문단 텍스트 — python-docx `Paragraph.text` **＋ 콘텐츠 컨트롤(`w:sdt`) 안의 런**.

    `p.text` 는 `w:p` **직속** `w:r` 만 이어붙인다. 그래서 값이 `w:sdt` 로 감싸인 자리를
    통째로 놓쳤고, 재작성 경로가 그 문단을 다시 쓰면서 **문장 한복판이 비었다**
    (실측: 템플릿 `이 문서는 [Project Name] 프로젝트를 위한…` → 산출물
    `이 문서는  프로젝트를 위한…`). 구멍은 오타로 읽혀 검토에서 넘어간다.

    ⚠ 텍스트박스(`w:txbxContent`)와 하이퍼링크(`w:hyperlink`)는 **제외한다**:
      - 텍스트박스에는 표준 템플릿의 "■ 작성 내용" **작성 지침 상자**가 들어 있다.
        본문으로 끌어오면 납품 문서에 지침이 실린다.
      - 하이퍼링크에는 템플릿의 **옛 목차 항목**이 산다. 포함하면 생성기가 새로 넣는
        목차와 별개로 평문 목차가 한 벌 더 복제된다.
      둘 다 `p.text` 도 읽지 않으므로 이 제외는 **현행 동작 그대로**다.
    """
    try:
        nodes = p_el.xpath(
            ".//w:t[not(ancestor::w:txbxContent) and not(ancestor::w:hyperlink)]")
    except Exception:   # noqa: BLE001 - XPath 미지원 요소는 텍스트 없음으로
        return ""
    return "".join(n.text or "" for n in nodes)


def _append_body_block(doc, el, picture_sink=None) -> None:
    """원본 요소를 본문 끝(단, `w:sectPr` **앞**)에 되붙인다.

    ⚠ `body.append(el)` 을 쓰면 `w:sectPr` **뒤**로 간다. python-docx 의
      `add_paragraph`/`add_table` 은 스키마 순서를 지켜 `sectPr` 앞에 넣으므로,
      두 방식을 섞으면 되살린 블록만 문서 맨 끝으로 밀린다 — 실측으로 표지와
      이력·참조 표가 그렇게 문서 끝(구역 속성 뒤)으로 갔다.
    """
    from docx.oxml.ns import qn  # type: ignore
    body = doc._body._element  # type: ignore[attr-defined]
    sect = body.find(qn("w:sectPr"))
    if sect is not None:
        sect.addprevious(el)
    else:
        body.append(el)
    if picture_sink is not None:
        picture_sink.note_appended(el)      # (R53 N27-c) 되붙인 요소 안의 숫자 `@id` 가 그림 id 최대값을 올릴 수 있다


def _fill_bracket_project_name(doc, project: str) -> int:
    """템플릿의 `[Project Name]` 표식을 실제 프로젝트명으로 채운다.

    표준 템플릿은 표지·Introduction 의 프로젝트명 자리에 이 표식을 두고, 콘텐츠
    컨트롤(`w:sdt`)로 `dc:subject` 에 바인딩해 둔다(실측 8곳). 표식을 **지우기만**
    하면 `이 문서는  프로젝트를 위한…` 처럼 문장에 구멍이 남고, 구멍은 오타로 읽혀
    검토에서 그냥 넘어간다.

    ⚠ 값이 없거나 폴백 기본값(`UDS Spec`)이면 **표식을 그대로 둔다** — 없는 이름을
      지어내지 않는다(`[Project Name]` 이 그대로 보이면 채워야 할 자리임이 드러난다).
    ⚠ 토큰 치환 경로와 재작성 경로 **둘 다** 이 함수를 지난다. 재작성 경로만 고치면
      토큰 템플릿을 쓰는 프로젝트에서 같은 구멍이 남는다.

    Returns:
        치환한 `w:t` 노드 수.
    """
    from docx.oxml.ns import qn  # type: ignore
    name = str(project or "").strip()
    if not name or name.lower() == "uds spec":
        return 0
    try:
        body = doc._body._element  # type: ignore[attr-defined]
    except Exception:   # noqa: BLE001 - 채우기 실패가 생성을 막지는 않는다
        return 0
    n = 0
    for t in body.iter(qn("w:t")):
        if t.text and "[Project Name]" in t.text:
            t.text = t.text.replace("[Project Name]", name)
            n += 1
    if n:
        try:
            # 표지 sdt 가 `dc:subject` 에 바인딩돼 있어, 문서 속성도 맞춰 두면
            # Word 가 필드를 갱신해도 같은 값이 나온다.
            doc.core_properties.subject = name
        except Exception:   # noqa: BLE001 - 보너스라 실패해도 무방
            pass
    return n


def _is_toc_sdt(sdt_el) -> bool:
    """목차 빌딩블록인가 — `docPartGallery` 가 Word 의 표준 표식이다.

    표지는 `"Cover Pages"`, 목차는 `"Table of Contents"`. 목차 sdt 를 보존하면
    생성기가 새로 넣는 목차와 **두 벌**이 된다.
    """
    from docx.oxml.ns import qn  # type: ignore
    try:
        vals = [str(g.get(qn("w:val")) or "").strip().lower()
                for g in sdt_el.iter(qn("w:docPartGallery"))]
    except Exception:   # noqa: BLE001 - 표식을 못 읽으면 목차로 단정하지 않는다
        return False
    return any("table of contents" in v for v in vals)


def _iter_template_blocks(doc):
    """(하위호환) body 직속 `w:p`/`w:tbl` **래퍼 객체**만 문서 순서대로.

    ⚠ 이 이름의 계약은 **객체 리스트**다. `report_gen/validation.py` 두 곳이
      duck typing(`hasattr(block, "text")` / `hasattr(block, "rows")`)으로 소비하므로
      `(kind, obj)` 튜플로 바꾸면 **전부 조용히 건너뛴다** — 실제로 그렇게 바꿨다가
      SwCom 정본 diff 가 통째로 빈 리포트를 냈다(가드 9건이 잡았다).
      새 축(표지 등 raw 블록)은 아래 `_iter_body_blocks` 로 낸다.
    """
    return [obj for kind, obj in _iter_body_blocks(doc) if kind != "raw"]


def _iter_body_blocks(doc):
    """body 직속 자식을 **문서 순서대로** `(kind, obj)` 로 낸다.

    kind: `"para"`(Paragraph) · `"table"`(Table) · `"raw"`(그 밖의 블록 요소).

    ⚠ 오래 `w:p`/`w:tbl` 만 냈다. Word 는 **표지를 body 직속 `w:sdt`** 로 넣기 때문에
      (`docPartGallery="Cover Pages"`) 그 표지가 여기서 통째로 사라졌고, 재작성 경로는
      "정본을 쓰면 표지가 납품본과 같아진다" 고 공시하면서 실제로는 표지를 **잃었다**.
      실측: 표준 템플릿·정본 **둘 다 body[0] 이 표지 sdt**(정본은 `KJPDS02 / v2.08`).
      `w:sectPr`·북마크처럼 보이는 내용이 없는 자식은 계속 무시한다.
    """
    from docx.oxml.ns import qn  # type: ignore
    try:
        from docx.oxml.table import CT_Tbl  # type: ignore
        from docx.oxml.text.paragraph import CT_P  # type: ignore
        from docx.table import Table  # type: ignore
        from docx.text.paragraph import Paragraph  # type: ignore
    except Exception:
        return []
    parent = doc._body._element  # type: ignore[attr-defined]
    blocks = []
    for child in parent.iterchildren():
        if isinstance(child, CT_P):
            blocks.append(("para", Paragraph(child, doc)))
        elif isinstance(child, CT_Tbl):
            blocks.append(("table", Table(child, doc)))
        elif child.tag == qn("w:sdt") and not _is_toc_sdt(child):
            blocks.append(("raw", child))
    return blocks


_HEADER_KEYWORDS = frozenset({
    "file name",
    "version",
    "date",
    "note",
    "macro",
    "type",
    "define",
    "description",
    "parameter",
    "component",
    "function",
    "comment",
    "data name",
    "data type",
    "value range",
    "reset",
})


def _looks_like_header_row(cells: List[str]) -> bool:
    """1행이 헤더처럼 보이는가 — **관대하게** 본다(부분문자열).

    배너 셀(`[ Function Information ]`)처럼 라벨과 정확히 같지 않은 헤더가 실제로
    있어서, 여기서 엄격하게 보면 정상 표 1,035개가 판정을 잃는다(실측).
    """
    joined = " ".join(c.lower() for c in cells if c).strip()
    return any(k in joined for k in _HEADER_KEYWORDS)


def _is_header_label_row(cells: List[str]) -> bool:
    """2행이 **헤더의 둘째 줄**인가 — 엄격하게 본다(셀 완전일치).

    ⚠ 여기가 부분문자열이면 템플릿의 **예시 데이터 행**이 헤더로 굳는다. 데이터 행은
      긴 설명을 달고 다녀서 `type`·`version`·`reset` 같은 낱말이 값 안에 우연히 들어
      있기 때문이다 — 실측으로 `VERSION1`·`CPU_POWER_ON_RESET`·`APP_FIRMWARE_VERSION_ADDR`
      같은 **남의 값 6행이 산출물에 그대로 실렸다**. 헤더의 둘째 줄은 순수 라벨
      (`ID`/`Name`/`Type`)이므로 셀 하나라도 라벨과 **정확히** 같을 것을 요구한다.
      정본·표준 템플릿 1,194표 전수 대조: 의도한 7건만 바뀌고 회귀 0건.
    """
    for c in cells:
        if re.sub(r"\s+", " ", str(c or "")).strip().lower() in _HEADER_KEYWORDS:
            return True
    return False


def _extract_template_blocks(doc) -> List[Tuple[str, Any]]:
    blocks: List[Tuple[str, Any]] = []
    stack: List[str] = []
    for kind_in, item in _iter_body_blocks(doc):
        if kind_in == "raw":
            # 표지 같은 구조 블록은 **원본 요소 그대로** 들고 간다. 텍스트로 풀면
            # 그림·서식·바인딩이 다 날아간다. 참조만 잡으므로 복사 비용은 없다
            # (`_clear_docx_body` 가 detach 해도 이 참조가 요소를 살려 둔다).
            blocks.append(("raw", item))
            continue
        if kind_in == "para":
            text = _para_text(item._element).strip()
            if not text or not item.style:
                continue
            name = str(getattr(item.style, "name", "") or "")
            if not name.startswith("Heading"):
                blocks.append(("para", {"text": text, "style": name}))
                continue
            level = 2
            parts = re.findall(r"\d+", name)
            if parts:
                try:
                    level = max(1, int(parts[0]))
                except Exception:
                    level = 2
            if len(stack) >= level:
                stack = stack[: level - 1]
            stack.append(text)
            blocks.append(("heading", (level, text)))
        elif kind_in == "table":
            try:
                rows = len(item.rows)
                cols = len(item.columns)
                style = getattr(item, "style", None)
                header_rows: List[List[str]] = []
                for r in item.rows[:2]:
                    header_rows.append([c.text.strip() for c in r.cells])
                if len(header_rows) == 2:
                    if (_looks_like_header_row(header_rows[0])
                            and not _is_header_label_row(header_rows[1])):
                        header_rows = header_rows[:1]
                # 6번째로 **원본 표 요소**를 들고 간다. 생성기가 채우지 않는 표
                # (이력·참조 등)는 모양만 복제하면 데이터 행이 빈칸으로 나가는데,
                # 빈칸은 "이력 없음" 으로 읽힌다(실측: 정본 이력 29행이 헤더만 남음).
                blocks.append(("table",
                               (rows, cols, style, header_rows, list(stack), item._element)))
            except Exception:
                continue
    return blocks


def _extract_template_section_block_map(doc) -> Dict[str, List[Dict[str, str]]]:
    """Like _extract_template_section_map but preserves per-paragraph style.

    Returned dict: heading_title_lower -> list of {"text", "style"}.
    Used by the rebuild path (1장) to keep List Paragraph / bullet styles
    from the tokenized template instead of flattening to Normal.
    """
    section_map: Dict[str, List[Dict[str, str]]] = {}
    current_title = ""
    current_entries: List[Dict[str, str]] = []
    for p in doc.paragraphs:
        text = _para_text(p._element).strip()
        style_name = str(getattr(p.style, "name", "") or "")
        level = 0
        if text and style_name.startswith("Heading"):
            parts = re.findall(r"\d+", style_name)
            try:
                level = max(1, int(parts[0])) if parts else 1
            except Exception:
                level = 1
        if level > 0:
            if current_title:
                while (
                    len(current_entries) >= 2
                    and not current_entries[-1]["text"]
                    and not current_entries[-2]["text"]
                ):
                    current_entries.pop()
                section_map[current_title.lower()] = list(current_entries)
            current_title = text
            current_entries = []
            continue
        if not current_title:
            continue
        if not text and not current_entries:
            continue
        if not text and current_entries and not current_entries[-1]["text"]:
            continue
        current_entries.append({"text": text, "style": style_name})
    if current_title and current_title.lower() not in section_map:
        while (
            len(current_entries) >= 2
            and not current_entries[-1]["text"]
            and not current_entries[-2]["text"]
        ):
            current_entries.pop()
        section_map[current_title.lower()] = list(current_entries)
    return section_map


def _add_docx_section_paragraphs(doc, entries: List[Dict[str, str]]) -> None:
    has_text = any(str(e.get("text") or "") for e in entries)
    if not entries or not has_text:
        doc.add_paragraph("N/A")
        return
    for entry in entries:
        text = str(entry.get("text") or "")
        style = str(entry.get("style") or "").strip()
        try:
            if text and style:
                doc.add_paragraph(text, style=style)
            elif text:
                doc.add_paragraph(text)
            else:
                doc.add_paragraph("")
        except Exception:
            doc.add_paragraph(text)


def _extract_template_section_map(doc) -> Dict[str, str]:
    section_map: Dict[str, str] = {}
    current_title = ""
    current_lines: List[str] = []
    for p in doc.paragraphs:
        text = _para_text(p._element).strip()
        if not text:
            continue
        style = str(getattr(p.style, "name", "") or "")
        level = 0
        if style.startswith("Heading"):
            parts = re.findall(r"\d+", style)
            if parts:
                try:
                    level = max(1, int(parts[0]))
                except Exception:
                    level = 1
            else:
                level = 1
        if level > 0:
            if current_title:
                section_map[current_title.lower()] = "\n".join(current_lines).strip()
            current_title = text
            current_lines = []
            continue
        current_lines.append(text)
    if current_title and current_title.lower() not in section_map:
        section_map[current_title.lower()] = "\n".join(current_lines).strip()
    return section_map


def _add_blank_table(
    doc,
    rows: int,
    cols: int,
    style: Any = None,
    header_rows: Optional[List[List[str]]] = None,
    data_rows: Optional[List[List[str]]] = None,
) -> Any:
    if rows <= 0 or cols <= 0:
        return None
    table = doc.add_table(rows=rows, cols=cols)
    try:
        if style:
            table.style = style
    except Exception:
        pass
    # 새 표는 병합 없는 균일 격자라 `[c + r * cols]` 가 곧 `table.cell(r, c)` 다 — 단, 그리드는 **한 번만** 만든다.
    #   예전엔 셀마다 `table.cell()` 을 불러 1,000행 표에서 셀 수의 제곱으로 돌았다(라이브 프로파일 DOCX 시간의 38.6%).
    grid = _grid_cells(table)
    row_offset = 0
    if header_rows:
        for r_idx, row in enumerate(header_rows):
            if r_idx >= rows:
                break
            for c_idx, val in enumerate(row[:cols]):
                grid[c_idx + r_idx * cols].text = val or ""
        row_offset = min(len(header_rows), rows)
    if data_rows:
        max_rows = rows - row_offset
        if len(data_rows) > max_rows:
            # ⚠ 여기서 잘린 행은 **아무 데도 안 남는다**. 실측(표준 템플릿 v0.10):
            #   호출부가 템플릿 행수를 넘기는 바람에 6개 표에서 1,144행이 사라졌고
            #   `Software Unit Tables` 는 함수 57개 중 15개만 실렸는데, 경고가 없어
            #   문서만 보면 "함수가 15개뿐인 프로젝트" 로 읽혔다. 호출부는 전부
            #   데이터에 맞춰 잡도록 고쳤지만, 새 호출부가 다시 그러면 보이게 한다.
            _logger.warning(
                "표 행수 부족으로 데이터 %d행 중 %d행만 기록한다(-%d행) — "
                "표 크기를 데이터에 맞춰 잡을 것",
                len(data_rows), max(max_rows, 0), len(data_rows) - max(max_rows, 0),
            )
        for r_idx, row in enumerate(data_rows[:max_rows]):
            for c_idx, val in enumerate(row[:cols]):
                grid[c_idx + (row_offset + r_idx) * cols].text = str(val) if val is not None else ""
    # (R47-j) 예전의 뒷정리 루프(`if c.text is None: c.text = ""`)는 지웠다 — `_Cell.text` 는 None 을 내지 않아 한 번도
    #   쓰지 않는 루프였고, `table.rows[r]` 인덱싱이 행마다 전 행을 다시 만들어 비용만 냈다(XML 동일 — 가드가 대조한다).
    return table


# 참조 SUDS 신원 판정용 — 문서 종류/일반 명사는 프로젝트 식별자가 아니다.
# ⚠ 2026-08-07: 정의가 `report_gen/doc_kind.py` 로 **승격**됐다(SCM 연결 문서 신원 검사도
#   같은 판정을 쓴다 — 사본을 두면 이 저장소 단골인 "한쪽만 수정"이 된다).
#   아래 두 이름은 기존 참조를 위한 별칭일 뿐이다.
from report_gen.doc_kind import (  # noqa: E402 — 별칭 바인딩 지점에 두어 출처를 명시
    PROJECT_TOKEN_STOPWORDS,
    project_tokens,
)

_REF_TOKEN_STOPWORDS = PROJECT_TOKEN_STOPWORDS
# ISO 26262 등급 어휘. 참조 문서 파싱이 어긋나면 프로토타입 문자열 같은 게 ASIL 로 들어온다
# — 실측: 참조 SUDS 416 블록 중 1건이 `asil='void s_Init_SystemManagementFunc( void )'`.
_VALID_ASIL = frozenset({"A", "B", "C", "D", "QM"})


# 토큰 추출도 doc_kind 단일 구현을 그대로 쓴다(별칭).
_project_tokens = project_tokens


def _reference_identity_verdict(uds_payload: Any, ref_path: Path) -> Dict[str, Any]:
    """참조 SUDS 가 **이 프로젝트의** 문서인지 판정한다.

    ⚠ 왜 필요한가 — 실측(2026-07-31):
    `config.UDS_REF_SUDS_PATH` 의 기본값은 저장소 `docs/` 의 **HDPDM01 SUDS**(40.7MB)다.
    그런데 생성 시 이 문서를 무조건 읽어 **함수명만으로** 매칭해 대상 프로젝트의 함수에
    `asil`·`related`·`description`·`logic` 등을 덧씌웠다. 참조 문서는 416 블록 전부가
    `asil` 을 갖고 있고(**A 280 / QM 135**), 다른 프로젝트에서 이름이 겹치기만 하면
    그 등급이 들어간다. ASIL 하향은 ISO 26262 에서 가장 위험한 방향의 오류다.

    같은 패턴을 이 저장소가 이미 두 번 고쳤다 — `backend/routers/local.py::_pick_doc_path`
    ("지정 문서를 못 읽으면 저장소 docs/ 로 바꿔치기") 와 SUTS ASIL 이 HDPDM01 로 채워지던
    건. 여기가 남은 사이트다.

    Returns:
        `same_project` — `True`(확인됨) / `False`(다름) / `None`(판정 불가).
        판정 불가는 **확인됨이 아니다** — 안전 필드는 fail-closed 로 막는다.
    """
    ref_tokens = _project_tokens(ref_path.stem)
    payload_tokens: Set[str] = set()
    if isinstance(uds_payload, dict):
        for key in ("project_name", "module_name"):
            payload_tokens |= _project_tokens(uds_payload.get(key))
        for p in (uds_payload.get("source_docs") or [])[:50]:
            payload_tokens |= _project_tokens(Path(str(p)).stem)
        summary = uds_payload.get("summary")
        if isinstance(summary, dict):
            payload_tokens |= _project_tokens(summary.get("project"))
        # (R47-e 리뷰 W1) 부모가 레지스트리 항목 id 를 **전용 키**로 준다 — 표지 문자열과 분리된 신원 입력.
        payload_tokens |= _project_tokens(uds_payload.get("reference_identity_hint"))

    if not ref_tokens:
        return {"same_project": None, "reason": "ref_no_token",
                "ref_tokens": sorted(ref_tokens), "payload_tokens": sorted(payload_tokens)}
    if not payload_tokens:
        return {"same_project": None, "reason": "payload_no_token",
                "ref_tokens": sorted(ref_tokens), "payload_tokens": sorted(payload_tokens)}
    shared = ref_tokens & payload_tokens
    return {
        "same_project": bool(shared),
        "reason": "token_match" if shared else "token_mismatch",
        "ref_tokens": sorted(ref_tokens),
        "payload_tokens": sorted(payload_tokens),
        "shared_tokens": sorted(shared),
    }


def gen_stats_path(output_path: str) -> Path:
    """생성 통계 sidecar 경로 — `<out>.gen_stats.json`.

    ⚠ **파일로 남겨야 하는 이유**: 프로덕션 경로는 `backend/helpers/uds.py:1194` 의
    exec 문자열을 **서브프로세스**로 돌리고 반환값을 버린다. 성공 판정도
    `returncode == 0 and out_path.exists() and size > 0` 뿐이다. 그래서 in-process
    `stats_out` 만으로는 호출자에게 아무것도 못 전달한다.
    """
    return Path(str(output_path) + ".gen_stats.json")


def enriched_function_details_path(output_path: str) -> Path:
    """빌더가 **참조 보강까지 끝낸** `function_details` 를 남기는 사이드카 — `<out>.docx.function_details.json`. (R47 N27)

    ⚠ 왜 필요한가: 참조 SwUDS 보강(ASIL·Related·서술·구조 축)은 **이 서브프로세스 안의** `function_details`
      에 일어나는데, 게이트가 읽는 `<out>.payload.json` 은 **부모 프로세스가 보강 전 객체**로 쓴다. 그래서 R47
      라이브에서 문서는 ASIL 82.8% 인데 게이트는 23.8% 였다 — 게이트가 문서가 아니라 파서 출력을 재고 있었다.
      부모는 이 파일을 payload 에 병합한 뒤 사이드카를 쓴다(`backend.helpers.uds.merge_enriched_function_details`).
    """
    return Path(str(output_path) + ".function_details.json")


def _write_enriched_function_details(output_path: str, function_details: Dict[str, Any],
                                     ref_stats: Dict[str, Any]) -> None:
    """실패해도 문서 생성을 깨지 않는다 — 대신 부모가 "보강본 없음" 을 payload 에 적는다."""
    try:
        enriched_function_details_path(output_path).write_text(
            json.dumps({
                "source": "docx_builder",
                "reference_suds": ref_stats,
                "function_details": function_details,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:   # noqa: BLE001 - 사이드카 실패가 산출물을 막아선 안 된다
        _logger.warning("보강 function_details 사이드카 기록 실패 %s: %s", output_path, e)


_STAT_SAMPLE_CAP = 50


def _safety_value_key(value: Any, field: str = "related") -> str:
    """(R50 N38) ASIL·Related 값의 **비교 키** — 표기가 달라도 같은 값이면 같다.

    정본이 이미 있던 값을 덮을 때 "같은 값(출처만 승격)" 과 "다른 값(충돌)" 을 가르는 데만 쓴다 — 결과값이 아니라
    **충돌 계수**가 걸린 판정이라, 표기 변형을 충돌로 세면 "설계 문서와 정본이 어긋난 함수 N건" 이 거짓 주장이 된다.
    - `asil`: `ASIL B`·`asil-b`·`B` 는 같다(리뷰 W5 — `cur` 는 SwDS 파싱 원문이라 접두어가 흔하다).
    - `related`: 구분자·나열 순서·중복을 무시한 토큰 **집합**(`SwFn_25, SwCom_03` ≡ `SwCom_03 / SwFn_25`).
    """
    raw = str(value or "").strip().upper()
    if field == "asil":
        return re.sub(r"[^A-Z0-9]", "", re.sub(r"^\s*ASIL[\s_-]*", "", raw))
    toks = {t for t in re.split(r"[\s,;/]+", raw) if t}
    return ",".join(sorted(toks))


_REF_AXES = ("asil", "related", "description", "precondition", "logic",
             "inputs", "outputs", "globals_static", "globals_global", "called", "calling")
_REF_NO_OPINION = frozenset({"", "TBD", "NA", "N/A", "-", "NONE"})


def _reference_opinion(value: Any, axis: str) -> str:
    """정본 블록 한 축의 **의견** 정규화 키 — 자리표시자(빈칸·TBD·N/A·-)는 의견 없음(`""`). (R51 리뷰 W2)

    같은 이름 블록끼리 "다른 값을 말하는가" 를 잴 때, 적용 경로가 버리는 값(`asil` 은 `_VALID_ASIL` 밖, 빈칸류)을
    판정 경로만 "의견" 으로 세면 사본 절의 `TBD` 가 유효한 등급을 막고 검토자에게 "정본을 고쳐라" 까지 올린다.
    """
    whole = " ".join(str(value or "").split()).upper() if not isinstance(value, (list, tuple)) else None
    if whole is not None and whole in _REF_NO_OPINION:
        return ""      # `N/A` 는 토큰으로 쪼개면 `A`·`N` 이 된다 — 통째로 먼저 본다
    if axis == "asil":
        k = _safety_value_key(value, "asil")
        return k if k in _VALID_ASIL else ""
    if axis == "related":
        toks = [t for t in _safety_value_key(value, "related").split(",") if t and t not in _REF_NO_OPINION]
        return ",".join(toks)
    if isinstance(value, (list, tuple)):
        return "\n".join(" ".join(str(v).split()) for v in value if str(v).strip())
    return " ".join(str(value or "").split())


def _sibling_axis_conflicts(siblings: List[str], ref_map: Dict[str, Any]) -> Set[str]:
    """같은 이름 정본 블록들이 서로 **다른 의견**을 내는 축. (R51 리뷰 W3 — 갈린 축만 막고 같은 축은 싣는다)"""
    out: Set[str] = set()
    for axis in _REF_AXES:
        opinions = {_reference_opinion((ref_map.get(s) or {}).get(axis), axis) for s in siblings} - {""}
        if len(opinions) > 1:
            out.add(axis)
    return out


def _resolve_reference_target(
    fid: str,
    block: Any,
    function_details: Dict[str, Any],
    function_details_by_name: Any,
    ref_blocks_by_name: Dict[str, List[str]],
    ref_map: Dict[str, Any],
    stats: Dict[str, Any],
    seen_names: Set[str],
) -> Tuple[Optional[Dict[str, Any]], Set[str]]:
    """정본 SwUDS 블록 하나가 payload 의 어느 함수인가 — **이름**으로 찾는다. (R51 N40)

    ⚠ 왜 ID 가 아닌가: 생성 ID(`SwUFn_{모듈}{일련}`)는 소스 스캔 순서로 붙고, 정본 ID 는 그 문서의 것이다. 두 번호는
      서로 무관하다. 실측(kjpds02_pv 정본 v3.03 × run 2080, 2026-09-15): 옛 "ID 먼저, 없으면 이름" 규칙으로 ID 가
      맞은 819 블록 중 **773 이 이름이 다른 함수**였다(정본 SwUFn_0101 = main, 생성본 SwUFn_0101 = ADC_MONITOR_Enable).
      그 엉뚱한 블록의 ASIL 763 · Related 762 · precondition 729 · inputs 368 · outputs 372 · called 339 건이
      다른 함수에 실려 있었다(Initial commit 이래). "정본 자기 충돌 77건" 은 뒤에 온 **올바른(이름) 블록**이 막힌 수였다.
      ID 는 판정에 쓰지 않는다 — 우연히 같은 번호를 안전값 충돌의 결정 근거로 삼는 것은 같은 오류다(리뷰 W1). 이름과
      ID 가 함께 맞은 건수(`by_name_and_id`)는 계수로만 남긴다.

    같은 이름 블록이 여럿이면(정본이 한 함수를 두 절에 실은 경우) **축별**로 본다: 서로 같은 의견인 축은 싣고, 갈린 축만
    막는다(`blocked_axes`). ASIL·Related 가 갈리면 `ambiguous_names` + 표본으로 공시 — 첫 블록을 고르면 침묵 판정이다
    (ASIL 지어내기 금지와 같은 축). 자리표시자(TBD·N/A)는 의견이 아니다(`_reference_opinion`).

    반환: `(대상 함수 dict 또는 None, 막힌 축 집합)`. None 이면 사유는 `stats` 계수에 남는다.
    """
    raw_name = str((block or {}).get("name") or "")
    name = _normalize_symbol_name(raw_name).lower()
    if not name:
        stats["unnamed_blocks"] += 1
        return None, set()
    target = None
    if isinstance(function_details_by_name, dict):
        target = function_details_by_name.get(name)
        if not isinstance(target, dict):
            target = function_details_by_name.get(raw_name.strip().lower())
    if not isinstance(target, dict):
        stats["unmatched_blocks"] += 1
        return None, set()
    _by_id = function_details.get(fid) if isinstance(function_details, dict) else None
    if isinstance(_by_id, dict) and _by_id is not target \
            and _normalize_symbol_name(str(_by_id.get("name") or "")).lower() != name:
        # 정본 ID 가 payload 의 **다른** 함수를 가리킨다 — 옛 ID 우선 매칭이 오염을 만들던 바로 그 경우.
        stats["id_collision_blocks"] += 1
    tid = str(target.get("id") or "")
    blocked: Set[str] = set()
    siblings = ref_blocks_by_name.get(name) or [fid]
    if len(siblings) > 1:
        blocked = _sibling_axis_conflicts(siblings, ref_map)
        if blocked and name not in seen_names:
            seen_names.add(name)
            _bx = stats["blocked_axes"]
            for _ax in blocked:
                _bx[_ax] = int(_bx.get(_ax, 0)) + 1
            if blocked & {"asil", "related"}:
                stats["ambiguous_names"] += 1
                if len(stats["ambiguous_sample"]) < _STAT_SAMPLE_CAP:
                    stats["ambiguous_sample"].append({
                        "name": str(target.get("name") or raw_name), "id": tid, "conflicting": sorted(blocked),
                        "blocks": [{"id": s, "asil": str((ref_map.get(s) or {}).get("asil") or ""),
                                    "related": str((ref_map.get(s) or {}).get("related") or "")[:80]} for s in siblings],
                    })
    if fid == tid:
        stats["by_name_and_id"] += 1
    else:
        stats["by_name"] += 1
    return target, blocked



def _write_gen_stats(output_path: str, stats: Dict[str, Any]) -> None:
    """생성 통계를 sidecar 로 남긴다. 실패해도 문서 생성을 깨지 않는다."""
    try:
        gen_stats_path(output_path).write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except Exception as e:   # noqa: BLE001 - 통계 기록 실패가 산출물을 막아선 안 된다
        _logger.warning("생성 통계 sidecar 기록 실패(%s) — 문서 자체는 정상", e)


def rejoin_function_maps(
    function_details: Any,
    function_details_by_name: Any,
) -> int:
    """`function_details_by_name` 값을 `function_details` 값과 **같은 객체로** 되돌린다.

    ## 왜 필요한가

    payload 는 두 맵을 **둘 다** 싣는다(`jenkins.py:2529` · `local.py:967`·`:1457` ·
    `backend/helpers/uds.py:1711` — 4개 빌더 전부). 라우터 시점에는 같은 dict 를 가리키지만,
    docx 생성은 `_run_docx_in_subprocess`(`backend/helpers/uds.py:1277`)가 payload 를
    **JSON 파일로 써서 서브프로세스에 넘기므로** 역직렬화 시점에 갈라진다.

    갈라진 뒤가 문제다. 해석 루프(주석-ASIL 승격 · SDS 주입 · `req_map` · 모듈 ASIL 상속)는
    `function_details` **전용**인데 렌더러 `_resolve_function_info` 는
    `function_details_by_name` 을 **먼저** 조회한다(키는 양쪽 다 소문자라 적중한다).
    즉 렌더러가 **enrich 되지 않은 사본**을 그린다 — 예외도 경고도 없다.

    ## 규칙

    - 이름(소문자)으로 이어 붙인다. 이후 모든 변경이 두 맵에 동시에 보인다.
    - `by_name` 에만 있는 항목(orphan)은 **버리지 않는다** — 지우면 렌더러가 찾던 함수가
      사라져 결함을 반대 방향으로 만든다.
    - 사본에만 있던 값은 잃지 않는다. 정본이 **비어 있는** 키만 옮긴다(덮어쓰지 않는다).

    Returns:
        재결합한 항목 수(0 이면 원래 같은 객체였다는 뜻 — 로컬 동기 경로 등).
    """
    if not isinstance(function_details, dict) or not isinstance(function_details_by_name, dict):
        return 0
    canonical: Dict[str, Dict[str, Any]] = {}
    for info in function_details.values():
        if isinstance(info, dict):
            nm = function_name_key(info.get("name"))
            if nm:
                canonical.setdefault(nm, info)
    rejoined = 0
    for nm, cur in list(function_details_by_name.items()):
        tgt = canonical.get(function_name_key(nm))
        if tgt is None or tgt is cur:
            continue
        if isinstance(cur, dict):
            for k, v in cur.items():
                if v not in (None, "", [], {}) and tgt.get(k) in (None, "", [], {}):
                    tgt[k] = v
        function_details_by_name[nm] = tgt
        rejoined += 1
    return rejoined


def generate_uds_docx(
    template_path: Optional[str],
    uds_payload: Dict[str, Any],
    output_path: str,
    ai_config: Optional[Dict[str, Any]] = None,
    *,
    stats_out: Optional[Dict[str, Any]] = None,
) -> str:
    """UDS DOCX 생성.

    Args:
        stats_out: 주면 생성 통계를 넣는다(additive). **같은 내용이 항상
            `<output_path>.gen_stats.json` 으로도 기록된다** — 프로덕션은 서브프로세스라
            반환값·in-process dict 가 호출자에게 닿지 않는다(`gen_stats_path` 참조).

    ⚠ 이 라이터는 **템플릿 주도**다: SwUFn 표는 템플릿의 heading 을 순회하며 payload 함수를
    찾아 채운다. 따라서 **템플릿에 heading 이 없는 payload 함수는 문서에 안 들어가고**,
    payload 에 없는 heading 은 빈 껍데기로 남는다. 둘 다 예전엔 **어디에도 보고되지 않았다.**

    실측(HDPDM01 실 템플릿 + 실 payload): payload 함수 432개 중 템플릿과 겹치는 337개만
    반영되고 **95개(22.0%)가 미반영**, 빈 heading **74개**. 그런데 프로덕션 성공 판정은
    "파일이 있고 0바이트가 아님" 뿐이라 이 상태가 `status: "success"` 로 기록됐다.
    """
    try:
        import docx  # type: ignore
    except Exception as exc:
        raise ImportError("python-docx 미설치로 DOCX 생성 불가") from exc

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    payload = _safe_dict(uds_payload)
    summary = _safe_dict(payload.get("summary", {}))
    project = payload.get("project_name") or summary.get("project") or summary.get("project_name") or "UDS Spec"
    generated_at = payload.get("generated_at") or datetime.now().isoformat(timespec="seconds")

    ai_sections = payload.get("ai_sections")
    overview = _apply_uds_rules(
        _merge_section_text(payload.get("overview", "") or "", ai_sections, "overview"),
        "overview",
    )
    requirements = _apply_uds_rules(
        _merge_section_text(payload.get("requirements", "") or "", ai_sections, "requirements"),
        "requirements",
    )
    interfaces = _apply_uds_rules(
        _merge_section_text(payload.get("interfaces", "") or "", ai_sections, "interfaces"),
        "interfaces",
    )
    uds_frames = _apply_uds_rules(
        _merge_section_text(payload.get("uds_frames", "") or "", ai_sections, "uds_frames"),
        "uds_frames",
    )
    notes_text = _merge_section_text(
        payload.get("notes", "") or "",
        ai_sections,
        "notes",
        append_base=True,
    )
    evidence_lines = _ai_evidence_lines(ai_sections)
    if evidence_lines:
        notes_text = "\n".join([notes_text, "Evidence:"] + evidence_lines).strip()
    quality_warnings = _ai_quality_warnings(ai_sections)
    if quality_warnings:
        notes_text = "\n".join([notes_text, "Quality warnings:"] + quality_warnings).strip()
    notes = _apply_uds_rules(notes_text, "notes")
    software_unit_design = payload.get("software_unit_design", "") or ""
    detailed_doc = _ai_document_text(ai_sections)
    # NOTE: payload["unit_structure"] / payload["global_data"] (파서가 만드는 **텍스트**)는
    # 여기서 의도적으로 쓰지 않는다 — 두 섹션은 텍스트가 아니라 구조화 데이터로 렌더된다:
    #   "unit structure" → _render_unit_structure_image(interface/internal functions) 다이어그램
    #   "global data"    → payload["global_vars"] 5열 테이블 (위 KEY_MOD_GLOBALS 주석 참조)
    # 그래서 아래 섹션 분기가 `pass` 다. 텍스트를 다시 배선하면 같은 내용이 중복 출력된다.
    interface_functions = payload.get("interface_functions", "") or ""
    internal_functions = payload.get("internal_functions", "") or ""
    function_table_rows = payload.get("function_table_rows", []) or []
    global_vars = payload.get("global_vars", []) or []
    static_vars = payload.get("static_vars", []) or []
    macro_defs = payload.get("macro_defs", []) or []
    calibration_params = payload.get("calibration_params", []) or []
    generation_warnings: List[str] = []
    function_details = payload.get("function_details", {}) or {}
    function_details_by_name = payload.get("function_details_by_name", {}) or {}
    # 소스루트 폴백이 파싱해 온 call_map 을 담아 둔다. 실제 call_map 확정은 아래
    # payload 우선 순서에서 한 번만 한다 (폴백 블록이 call_map 을 직접 건드리면
    # 아직 바인딩 전이라 UnboundLocalError 였고, 설령 됐어도 뒤에서 덮어썼다).
    _fallback_call_map: Dict[str, Any] = {}
    if (not function_details_by_name) and isinstance(function_details, dict):
        rebuilt: Dict[str, Dict[str, Any]] = {}
        for info in function_details.values():
            if not isinstance(info, dict):
                continue
            name = str(info.get("name") or "").strip().lower()
            if name:
                rebuilt[name] = info
        function_details_by_name = rebuilt
    if not function_details_by_name:
        source_root = payload.get("source_root") or payload.get("source_dir") or ""
        if source_root and Path(source_root).is_dir():
            try:
                from report_gen.uds_generator import generate_uds_source_sections  # lazy: heavy module
                fallback_src = generate_uds_source_sections(source_root)
                fb_details = fallback_src.get("function_details_by_name", {})
                if fb_details:
                    function_details_by_name = fb_details
                    function_details = fallback_src.get("function_details", {})
                    _fallback_call_map = fallback_src.get("call_map", {}) or {}
                    generation_warnings.append(f"Source root fallback used: {source_root}, found {len(fb_details)} functions")
            except Exception as e:
                generation_warnings.append(f"Source root fallback failed: {e}")
    if not function_details_by_name:
        rebuilt: Dict[str, Dict[str, Any]] = {}
        for ln in (payload.get("interface_functions", "") or "").splitlines() + (
            payload.get("internal_functions", "") or ""
        ).splitlines():
            sig = str(ln).strip()
            if not sig:
                continue
            m = re.match(r"([A-Za-z_]\w*)\s*\(", sig)
            name = m.group(1) if m else ""
            if not name:
                continue
            rebuilt[name.lower()] = {
                "id": "",
                "name": name,
                "prototype": sig,
                "description": "",
                "asil": "",
                "related": "",
                "inputs": _parse_signature_params(sig),
                "outputs": _parse_signature_outputs(sig, name),
                "precondition": "",
                "globals_global": [],
                "globals_static": [],
                "called": "",
                "logic": "",
            }
        if rebuilt:
            function_details_by_name = rebuilt

    _rejoined = rejoin_function_maps(function_details, function_details_by_name)
    if _rejoined:
        generation_warnings.append(
            f"function_details_by_name {_rejoined}건을 function_details 와 재결합했다"
            " (JSON 왕복으로 갈라진 사본 — 해석 루프 결과가 렌더러에 반영되지 않던 경로)"
        )

    # payload 우선, 없으면 소스루트 폴백이 파싱한 것 사용.
    call_map = payload.get("call_map", {}) or _fallback_call_map or {}
    if isinstance(call_map, dict) and call_map:
        normalized_call_map: Dict[str, List[str]] = {}
        for k, vals in call_map.items():
            nk = _normalize_symbol_name(str(k or "")).lower()
            if not nk:
                continue
            out_vals: List[str] = []
            for v in (vals or []):
                nv = _normalize_symbol_name(str(v or ""))
                if nv and nv not in out_vals:
                    out_vals.append(nv)
            normalized_call_map[nk] = out_vals
        if normalized_call_map:
            call_map = normalized_call_map

    calling_map: Dict[str, List[str]] = {}
    for caller, callees in call_map.items():
        for callee in callees:
            callee_lower = callee.lower() if callee else ""
            if callee_lower:
                calling_map.setdefault(callee_lower, [])
                if caller not in calling_map[callee_lower]:
                    calling_map[callee_lower].append(caller)

    def _get_2hop_calls(fn_name: str) -> List[str]:
        direct = call_map.get(fn_name.lower(), [])
        indirect: List[str] = []
        for d in direct:
            for hop2 in call_map.get(d.lower(), []):
                if hop2 not in direct and hop2 != fn_name and hop2 not in indirect:
                    indirect.append(hop2)
        return indirect

    def _get_2hop_callers(fn_name: str) -> List[str]:
        direct = calling_map.get(fn_name.lower(), [])
        indirect: List[str] = []
        for d in direct:
            for hop2 in calling_map.get(d.lower(), []):
                if hop2 not in direct and hop2 != fn_name and hop2 not in indirect:
                    indirect.append(hop2)
        return indirect

    call_relation_mode = str(payload.get("call_relation_mode") or "code").strip().lower()
    if call_relation_mode not in {"code", "document"}:
        call_relation_mode = "code"
    module_map = payload.get("module_map", {}) or {}
    globals_info_map = payload.get("globals_info_map", {}) or {}
    # 구조체/공용체 멤버의 타입·비트폭·자기 주석. 없으면 멤버 경로 행은 N/A 로 남는다
    # (베이스의 값을 물려주지 않는다 — `function_analyzer._member_grid_info`).
    struct_member_types = payload.get("struct_member_types", {}) or {}
    globals_format_order = payload.get("globals_format_order") or GLOBALS_FORMAT_ORDER
    globals_format_sep = payload.get("globals_format_sep") or GLOBALS_FORMAT_SEP
    globals_format_with_labels = payload.get("globals_format_with_labels", GLOBALS_FORMAT_WITH_LABELS)
    common_macros = payload.get("common_macros", []) or []
    type_defs = payload.get("type_defs", []) or []
    param_defs = payload.get("param_defs", []) or []
    version_defs = payload.get("version_defs", []) or []
    req_map = payload.get("req_map", {}) or {}
    sds_partition_map = payload.get("sds_partition_map", {}) or {}
    sds_module_map = payload.get("sds_module_map", {}) or {}

    sds_texts = payload.get("sds_texts") or []
    sds_doc_paths = payload.get("sds_doc_paths") or []
    for sds_path in sds_doc_paths:
        try:
            # (R52 리뷰 W3) 손복제 루프 → 단일 출처. 옛 루프는 새 키를 **별칭**으로 넣었다(입력 맵을 건드리면 같이 바뀜) — 헬퍼는 사본.
            _merge_sds_partition_map(sds_partition_map, _extract_sds_partition_map(sds_path))
        except Exception as exc:  # noqa: BLE001 — docx 파서 예외가 광범위. 사유는 로그로(옛 판은 침묵)
            _logger.warning("SwDS 파티션 맵 추출 실패 %s: %s", Path(str(sds_path)).name, type(exc).__name__)
    _sds_name_labels = {"partition name", "component name", "module name", "name"}
    _sds_asil_labels = {"asil"}
    _sds_desc_labels = {"description", "desc"}
    if not sds_partition_map and sds_texts:
        for sds_text in sds_texts:
            lines = (sds_text or "").splitlines()
            for i, line in enumerate(lines):
                m = re.search(r"(SwCom_\d+|Component\s+\d+|Module\s+\d+)", line, re.I)
                if m:
                    com_id = m.group(1)
                    name = ""
                    asil = ""
                    related = ""
                    desc_parts: List[str] = []
                    for j in range(i + 1, min(i + 30, len(lines))):
                        ln = lines[j].strip()
                        ln_lower = ln.lower()
                        if re.match(r"^(?:SwCom_\d+|Component\s+\d+|Module\s+\d+)", ln, re.I):
                            break
                        label = ln_lower.split(None, 1)[0] if ln_lower.split(None, 1) else ""
                        full_label = " ".join(ln_lower.split(None, 2)[:2]) if len(ln_lower.split(None, 2)) >= 2 else label
                        if full_label in _sds_name_labels or label in _sds_name_labels:
                            parts = ln.split(None, 2)
                            name = parts[-1].strip() if len(parts) > 1 else ""
                        elif label in _sds_asil_labels:
                            parts = ln.split(None, 1)
                            asil = parts[-1].strip() if len(parts) > 1 else ""
                        elif label in _sds_desc_labels or full_label in _sds_desc_labels:
                            parts = ln.split(None, 1)
                            desc_parts.append(parts[-1].strip() if len(parts) > 1 else "")
                        elif ln_lower.startswith("related"):
                            parts = ln.split(None, 1)
                            related = parts[-1].strip() if len(parts) > 1 else ""
                    key = (name or com_id).strip().lower()
                    key = re.sub(r"[^a-z0-9_/ ]", "", key).strip()
                    if key:
                        entry = sds_partition_map.get(key, {})
                        if asil and not entry.get("asil"):
                            entry["asil"] = asil
                        if related and not entry.get("related"):
                            entry["related"] = related
                        if desc_parts and not entry.get("description"):
                            entry["description"] = " ".join(desc_parts).strip()
                        sds_partition_map[key] = entry
    fn_module_map: Dict[str, str] = {}
    if function_table_rows:
        for row in function_table_rows:
            if not isinstance(row, list) or len(row) < 4:
                continue
            fid = str(row[2] or "").strip()
            mod = str(row[1] or "").strip()
            if fid and mod:
                fn_module_map[fid] = mod

    if isinstance(req_map, dict):
        for key, info in list(function_details_by_name.items()):
            if not isinstance(info, dict):
                continue
            req = req_map.get(key)
            if not req:
                fid = str(info.get("id") or "").strip().lower()
                if fid:
                    req = req_map.get(fid)
            if isinstance(req, dict):
                if not info.get("asil"):
                    info["asil"] = req.get("asil") or ""
                if not info.get("related"):
                    info["related"] = req.get("related") or ""

    # (R50 리뷰 C1) 모듈 상속의 **씨앗 우선순위** — 예전엔 dict 순서상 첫 non-TBD 값이 씨앗이라, SwDS 가 먼저 채운 QM 이
    #   정본 A 를 가진 형제보다 앞에 오면 모듈 전체가 QM 을 물려받았다(run 2079: module_inherit 1→672). 정본 채움 규칙과
    #   같은 순서로 씨앗을 고른다: 소스 주석 > 정본 > 설계·요구 문서 > 나머지. 같은 등급 안에서는 첫 함수.
    _SEED_RANK = {"comment": 0, "reference": 1, "uds": 1, "sds": 2, "srs": 2}

    def _inherit_module_asil(
        func_details: Dict[str, Any],
        module_map: Dict[str, str],
    ) -> Dict[str, int]:
        """빈칸(""/TBD) 함수에 같은 모듈의 씨앗 ASIL 을 물려준다. 반환 = 씨앗 출처별 상속 건수(gen_stats 공시용)."""
        module_seed: Dict[str, tuple] = {}     # mod -> (rank, asil, seed_source)
        for fid, finfo in func_details.items():
            if not isinstance(finfo, dict):
                continue
            asil = str(finfo.get("asil") or "").strip()
            if asil and asil not in {"TBD", ""}:
                mod = module_map.get(fid, "")
                if not mod:
                    continue
                src = canonical_source(finfo.get("asil_source"))
                rank = _SEED_RANK.get(src, 3)
                cur = module_seed.get(mod)
                if cur is None or rank < cur[0]:
                    module_seed[mod] = (rank, asil, src)
        by_seed: Dict[str, int] = {}
        for fid, finfo in func_details.items():
            if not isinstance(finfo, dict):
                continue
            asil = str(finfo.get("asil") or "").strip()
            if asil and asil not in {"TBD", ""}:
                continue
            mod = module_map.get(fid, "")
            seed = module_seed.get(mod)
            if seed:
                finfo["asil"] = seed[1]
                finfo["asil_source"] = "module_inherit"
                by_seed[seed[2]] = by_seed.get(seed[2], 0) + 1
            # ⚠ 예전엔 여기 `else: asil="QM"; asil_source="default"` 가 있었다. 지웠다.
            #   모듈 상속조차 못 찾았다는 건 **아무 근거도 없다**는 뜻이다. 그 상태를
            #   `QM`(안전 관련 아님)으로 적으면 근거의 부재가 등급 주장으로 둔갑한다.
            #   값을 지어내지 않는다 — 없으면 없는 대로, `TBD` 면 `TBD` 로 둔다.
            #   ⚠ 이 else 를 되살리면 상류(`requirements.py`)에서 같은 이유로 지운
            #   지어내기가 **여기서 다시 채워져** 상류 수정이 통째로 no-op 이 된다.
            #   네 사이트(`requirements.py`·여기·`function_analyzer.py`·`helpers/uds.py`)는
            #   한 세트다.
        return by_seed

    def _resolve_related_asil_desc(
        info: Dict[str, Any],
        sds_info: Optional[Dict[str, str]],
    ) -> None:
        # ⚠ 예전엔 세 축 모두 무조건 `"inference"` 였다. 실측(2026-07-31): 사람이 쓴 설명,
        #   실제 등급 `C`, 실제 `SwFn_07` 을 넣고 생성했더니 **셋 다 `inference`** 로 찍혔다
        #   — 아무것도 추론하지 않았는데 보고서 표에는 "추론" 이라고 나오고 점수는 0.60 이다.
        #   생산자(`report_gen/function_analyzer.py`)는 **자기가 한 행위에 묶어서** 라벨한다
        #   (합성했을 때만 `inference`, QM 을 채웠을 때만 `default`). 여기도 그 규약을 따른다.
        _d = str(info.get("description") or "")
        info.setdefault("description_source", "")
        if not str(info.get("description_source") or "").strip():
            info["description_source"] = unrecorded_source(
                _d, generic=bool(_d) and _is_generic_description(_d))
        if not str(info.get("asil_source") or "").strip():
            info["asil_source"] = unrecorded_source(info.get("asil"))
        if not str(info.get("related_source") or "").strip():
            info["related_source"] = unrecorded_source(info.get("related"))
        # `unknown` 도 약한 출처다 — 빠뜨리면 뒤따르는 주석·SDS·SRS 근거가 덮어쓰지 못해
        # "출처를 모른다" 가 "출처가 확정됐다" 처럼 굳는다(업그레이드 경로 차단).
        # 약한 출처 판정은 `report_gen/provenance.py` 단일 출처를 쓴다 —
        # 집합 리터럴을 여기 다시 적으면 새 라벨이 생길 때 한쪽만 갱신된다.
        c_asil = str(info.get("comment_asil") or "").strip()
        c_rel = str(info.get("comment_related") or "").strip()
        cur_asil_src = str(info.get("asil_source") or "").strip()
        cur_rel_src = str(info.get("related_source") or "").strip()
        if c_asil and is_weak_source(cur_asil_src):
            info["asil"] = c_asil
            info["asil_source"] = "comment"
        if c_rel and is_weak_source(cur_rel_src):
            info["related"] = c_rel
            info["related_source"] = "comment"
        if sds_info:
            cur_asil_src = str(info.get("asil_source") or "").strip()
            if is_weak_source(cur_asil_src):
                sds_asil = sds_info.get("asil")
                if sds_asil:
                    info["asil"] = sds_asil
                    info["asil_source"] = "sds"
            cur_rel_src = str(info.get("related_source") or "").strip()
            if is_weak_source(cur_rel_src):
                sds_related = sds_info.get("related")
                if sds_related:
                    info["related"] = sds_related
                    info["related_source"] = "sds"
            desc = str(info.get("description") or "").strip()
            if not desc or desc.startswith("Auto-generated from"):
                sds_desc = str(sds_info.get("description") or "").strip()
                if sds_desc:
                    info["description"] = sds_desc
                    info["description_source"] = "sds"
        if (not info.get("related")) or str(info.get("related")).strip() in {"", "TBD"}:
            text_blob = " ".join(
                [
                    str(info.get("description") or ""),
                    str(info.get("precondition") or ""),
                    str(info.get("called") or ""),
                ]
            )
            ids = re.findall(r"\b(Sw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK|Com)_\d+)\b", text_blob)
            if ids:
                seen = set()
                uniq_ids = []
                for rid in ids:
                    rid = rid.strip()
                    if not rid or rid in seen:
                        continue
                    seen.add(rid)
                    uniq_ids.append(rid)
                info["related"] = ", ".join(uniq_ids)
                info["related_source"] = "srs"
                for rid in ids:
                    req = req_map.get(rid.lower())
                    if req and req.get("asil"):
                        info["asil"] = req.get("asil")
                        info["asil_source"] = "srs"
                        break
        if (not info.get("related")) or str(info.get("related")).strip() in {"", "TBD"}:
            fid = str(info.get("id") or "").strip()
            mod = fn_module_map.get(fid, "")
            swcom_ids = re.findall(r"\bSwCom_\d+\b", str(mod), flags=re.I)
            if swcom_ids:
                seen_sw = []
                for sid in swcom_ids:
                    sid_norm = sid.replace("swcom", "SwCom")
                    if sid_norm not in seen_sw:
                        seen_sw.append(sid_norm)
                info["related"] = ", ".join(seen_sw)
                info["related_source"] = "inference"
        # 값을 **비우면서** 출처를 "추론" 이라고 적으면, 아무것도 없는 칸이 근거 0.60 을
        # 받는다. 근거가 없어서 비운 것이므로 `default`(근거 없음, 0.30)가 사실이다.
        # ⚠ 예전엔 여기서 `info["asil"] = ""` 로 **TBD 를 지웠다**. 값 대입을 뺐다.
        #   "미정"(TBD)과 "아예 없음"(빈칸)은 다른 상태다. 게다가 이 blanking 은
        #   같은 함수 끝(`:2505`)의 `UDS TBD residual` 경고가 세는 바로 그 값을
        #   **세기 전에 지워서**, `asil_tbd` 가 구조적으로 항상 0 이었다 —
        #   경고가 발화할 수 없는 잔량 카운터였다.
        #   출처 라벨은 유지한다: 값이 없으면 근거도 없으므로 `default`(0.30, 최약체)가
        #   사실이다(`inference` 0.60 을 주면 빈 칸이 추론 대접을 받는다).
        if (not info.get("asil")) or str(info.get("asil")).strip() in {"", "TBD"}:
            info["asil"] = str(info.get("asil") or "").strip()
            info["asil_source"] = "default"
        if (not info.get("related")) or str(info.get("related")).strip() in {"", "TBD"}:
            info["related"] = ""
            info["related_source"] = "default"

    # (R50 리뷰 C1) 모듈 상속 호출은 정본 채움 **뒤**로 옮겼다(아래 참조 블록 끝) — 여기 두면 SwDS 값이 씨앗이 되어 정본이
    #   못 닿는 형제 함수에 굳는다.

    for info in list(function_details.values()):
        if not isinstance(info, dict):
            continue
        sds_info = None
        if sds_partition_map:
            fid = str(info.get("id") or "").strip()
            fname = str(info.get("name") or "").strip().lower()
            mod = fn_module_map.get(fid, "")
            key = mod.lower().strip() if mod else ""
            mapped = str(sds_module_map.get(key, "") or "").strip().lower()
            sds_info = sds_partition_map.get(mapped) if mapped else None
            if sds_info is None and fname:
                sds_info = sds_partition_map.get(fname)
            if sds_info is None and key:
                sds_info = sds_partition_map.get(key)
            if sds_info is None and key:
                norm_key = re.sub(r"[^a-z0-9]", "", key)
                for k, v in sds_partition_map.items():
                    if key in k or k in key:
                        sds_info = v
                        break
                    norm_k = re.sub(r"[^a-z0-9]", "", k)
                    if norm_key and norm_k and (norm_key in norm_k or norm_k in norm_key):
                        sds_info = v
                        break
            if sds_info is None:
                fallback = sds_partition_map.get("application/ driver") or sds_partition_map.get("application/driver")
                if fallback:
                    sds_info = fallback
        _resolve_related_asil_desc(info, sds_info if isinstance(sds_info, dict) else None)
        desc = str(info.get("description") or "").strip()
        if desc.startswith("Function") and "|" in desc:
            desc = desc.split("|", 1)[-1].strip()
        if (not desc) or _is_generic_description(desc) or (desc.lower().startswith("function") and len(desc.split()) <= 3):
            desc = _enhance_description_text(
                str(info.get("name") or ""),
                _fallback_function_description(
                    str(info.get("name") or ""),
                    info.get("called") or info.get("calls_list") or [],
                ),
                info.get("called") or info.get("calls_list") or [],
            )
            if _is_generic_description(desc):
                desc = _enhance_function_description(
                    str(info.get("name") or ""),
                    info.get("called") or info.get("calls_list") or [],
                    str(info.get("module_name") or ""),
                )
            info["description_source"] = "inference"
        else:
            desc = _enhance_description_text(
                str(info.get("name") or ""),
                desc,
                info.get("called") or info.get("calls_list") or [],
            )
            if _is_generic_description(desc):
                desc = _enhance_function_description(
                    str(info.get("name") or ""),
                    info.get("called") or info.get("calls_list") or [],
                    str(info.get("module_name") or ""),
                )
                info["description_source"] = "inference"
        info["description"] = desc

    # ── RAG 기반 Description 보강 (inference인 함수에 대해 유사 함수 설명 참조) ──
    # 기본 off: 이 보강은 ASIL 문서(UDS)의 함수 설명 출력을 바꾸므로, opt-in
    # (UDS_RAG_DESC_ENRICH=1)일 때만 동작한다. 과거 존재하지 않는 KB load 메서드 호출로
    # AttributeError 가 나며 영구 dead 였다 — KnowledgeBase.__init__ 이 _load_all 로 로드한다.
    _rag_desc_applied = 0
    try:
        import config as _cfg
        _rag_enrich_on = bool(getattr(_cfg, "UDS_RAG_DESC_ENRICH", False))
        # 절대경로화(CWD 의존 제거, #14) + KB_GLOBAL_DIR 설정 시 get_kb 프로세스 캐시 재사용.
        _kb_store_env = str(os.environ.get("KB_STORE_DIR") or "").strip()
        _kb_global = str(getattr(_cfg, "KB_GLOBAL_DIR", "") or "").strip()
        if _kb_store_env:
            _kb_dir, _use_cache = Path(_kb_store_env).expanduser().resolve(), False
        elif _kb_global:
            _kb_dir, _use_cache = Path(_kb_global).expanduser().resolve(), True
        else:
            _kb_dir, _use_cache = Path("kb_store").expanduser().resolve(), False
        if _rag_enrich_on and _kb_dir.exists():
            if _use_cache:
                from workflow.rag import get_kb
                # 주(W2): KB_GLOBAL_DIR 설정 시 get_kb 는 인자를 무시하고 KB_GLOBAL_DIR 을
                # re-resolve(_kb_resolve_base_dir)하므로 같은 캐시 키로 프로세스 캐시 인스턴스를
                # 재사용한다(_kb_dir == KB_GLOBAL_DIR resolved 라 일치). 문서 간 _load_all 1회.
                _kb = get_kb(_kb_dir)
            else:
                from workflow.rag import KnowledgeBase
                _kb = KnowledgeBase(_kb_dir)
            # N× 비용 상한: inference 함수 cap(기본 300) + 동일 query search 메모이즈.
            _enrich_max = int(getattr(_cfg, "UDS_RAG_ENRICH_MAX_FUNCS", 300) or 300)
            _search_memo = {}
            _scanned = 0
            if _kb.data:
                for fid, info in function_details.items():
                    if not isinstance(info, dict):
                        continue
                    # 약한 출처면 RAG 로 보강한다(예전엔 `!= "inference"` 라 `unknown`·
                    # `default` 인 함수가 보강 대상에서 통째로 빠졌다).
                    if not is_weak_source(info.get("description_source")):
                        continue
                    if _scanned >= _enrich_max:
                        _logger.info("RAG enrich cap reached (%d funcs) — 나머지 skip", _enrich_max)
                        break
                    fname = str(info.get("name") or "").strip()
                    proto = str(info.get("prototype") or "").strip()
                    query = f"{fname} {proto}".strip()
                    if not query:
                        continue
                    _scanned += 1
                    if query in _search_memo:
                        results = _search_memo[query]
                    else:
                        results = _kb.search(query, top_k=3, tags=["uds_description", "code"])
                        if not results:
                            results = _kb.search(query, top_k=3)
                        _search_memo[query] = results
                    for r in results:
                        # KB 엔트리는 텍스트를 context/fix/error_clean 에 저장한다
                        # (add_document/_ensure_shape). 과거 text/content 키는 항상 빈값이라
                        # opt-in 시에도 보강이 inert 였다 — 올바른 키로 교정.
                        chunk_text = str(
                            r.get("context") or r.get("fix") or r.get("error_clean") or "",
                        ).strip()
                        if not chunk_text or len(chunk_text) < 10:
                            continue
                        lines = chunk_text.split("\n")
                        desc_candidate = ""
                        for line in lines:
                            line = line.strip()
                            if fname.lower() in line.lower() and len(line) > 15:
                                desc_candidate = line
                                break
                        if desc_candidate and not _is_generic_description(desc_candidate):
                            info["description"] = desc_candidate[:200]
                            info["description_source"] = "rag"
                            _rag_desc_applied += 1
                            break
                if _rag_desc_applied:
                    _logger.info("RAG description applied: %d functions", _rag_desc_applied)
    except Exception as e:
        _logger.debug("RAG description enhancement skipped: %s", e)

    # 레퍼런스 SUDS에서 Function 정보 보강
    ref_related_by_name: Dict[str, str] = {}
    from config import UDS_REF_SUDS_PATH
    ref_doc_path = Path(UDS_REF_SUDS_PATH)
    _ref_identity = _reference_identity_verdict(uds_payload, ref_doc_path)
    _ref_safety_ok = _ref_identity["same_project"] is True
    # (R47 N26) 어느 문서를 열었는지도 남긴다 — 신원 토큰만으론 검토자가 "어떤 파일이었나" 를 못 본다.
    #   `configured` 는 부모가 경로를 넘겼는가(빈 값 = 미지정/접근 실패), `document` 는 실제로 연 파일명
    #   (Cloudium 로컬화 사본도 원래 이름을 유지하므로 이름이 곧 정본 식별자다).
    _ref_configured = bool(str(UDS_REF_SUDS_PATH or "").strip())
    _ref_stats: Dict[str, Any] = {
        "identity": _ref_identity,
        "configured": _ref_configured,
        "document": ref_doc_path.name if (_ref_configured and ref_doc_path.is_file()) else None,
        # (R47-d 리뷰 I3) 누가 이 문서를 골랐나 — 부모가 payload 에 남긴 출처("form" / "registry:<id>")를 그대로 베낀다.
        #   없으면 None(구 호출부·jenkins 경로). 로그에만 있던 출처가 사이드카→근거 화면까지 간다.
        "origin": (str(uds_payload.get("reference_suds_origin")).strip() or None)
        if isinstance(uds_payload, dict) and uds_payload.get("reference_suds_origin") else None,
        # (R47-e N30) 폼↔레지스트리 대조 상태 "same"/"differs"/"unavailable:<사유>"(폼 없으면 None) — null 하나로 접지 않는다(리뷰 W2).
        "registry_compare": (str(uds_payload.get("reference_suds_registry_compare")).strip() or None)
        if isinstance(uds_payload, dict) and uds_payload.get("reference_suds_registry_compare") else None,
        # (R47-e N30) 지정 경로가 레지스트리 정본과 다른 파일이었나 — `{"scm_id","form","registry"}`(파일명) 또는 None.
        "registry_mismatch": dict(uds_payload["reference_suds_registry_mismatch"])
        if isinstance(uds_payload, dict) and isinstance(uds_payload.get("reference_suds_registry_mismatch"), dict) else None,
        "safety_fields_applied": 0,
        "safety_fields_blocked": 0,
        # (R50 N38) 정본이 **이미 있던 값을 덮은** 안전축 — 빈칸 채움과 다른 사실이다. `overridden` 은 이전 출처별
        #   건수(`{"sds": 327, "module_inherit": …}`), `agreed` 는 값이 같아 출처만 정본으로 올린 건수, `sample` 은
        #   충돌 표본(캡). 라이브 run 2079 의 ASIL 변경 327건(A→QM 45·QM→A 40·TBD→A 215·TBD→QM 27)이 이 칸에 보였어야 했다.
        "safety_fields_agreed": 0,
        "safety_fields_overridden": {},
        "safety_conflicts_sample": [],
        # (리뷰 I1) `safety_fields_applied` 는 빈칸 채움 + 동의 승격 + 덮어쓰기의 합이 됐다 — 빈칸 채움만 따로 센다(구판 비교용).
        "safety_fields_blank_filled": 0,
        # (리뷰 W1) 정본과 값이 다른데 지켜진 출처(comment/uds)별 건수 — 정본을 막은 쪽의 충돌.
        "safety_fields_kept_conflict": {},
        # (R51 N40) 정본 블록→함수 매칭 계수. 매칭 키는 **이름**이다(`_resolve_reference_target` docstring 의 실측 — ID 로 맞은
        #   819 중 773 이 다른 함수). `id_collision_blocks` = 정본 ID 가 payload 의 다른 함수를 가리킨 블록(정본 번호 ≠ 생성 번호의
        #   증거), `ambiguous_names` = 같은 이름 블록이 서로 다른 값을 말해 **적용하지 않은** 함수(정본 문서 품질).
        "matching": {
            "by_name": 0, "by_name_and_id": 0, "id_collision_blocks": 0, "unmatched_blocks": 0, "unnamed_blocks": 0,
            "blocked_axes": {}, "ambiguous_names": 0, "ambiguous_sample": [],
        },
        "descriptive_fields_applied": 0,
        "invalid_asil_rejected": 0,
        # ⚠ 아래 6축은 예전엔 **계수에서 통째로 빠져** 있었다. `descriptive_fields_applied`
        #    는 description/precondition/logic 만 세는데, 실제로 참조 문서가 덧씌우는 축은
        #    11개다. 즉 sidecar 의 `reference_suds` 는 "무엇이 적용됐나" 를 묻는 기록인데
        #    절반 이상이 안 보였다 — 남의 프로젝트 문서에서 온 입출력·전역·호출관계가
        #    무기록으로 들어간다. 이 상태로는 "신원 불일치면 아예 안 읽어도 되는가"(성능)
        #    조차 판정할 수 없다: 적용량이 0인지 아닌지를 모르기 때문이다.
        "structural_fields_applied": {
            "inputs": 0, "outputs": 0, "globals_static": 0,
            "globals_global": 0, "called": 0, "calling": 0,
        },
        # 신원 미확인이라 **적용하지 않은** 구조 축. 0 이 아닌데 기록이 없으면 산출물
        # 검토자는 "적용할 게 없었다" 와 "막았다" 를 구분할 수 없다.
        "structural_fields_blocked": {
            "inputs": 0, "outputs": 0, "globals_static": 0,
            "globals_global": 0, "called": 0, "calling": 0,
        },
    }
    # (R47 리뷰 W1) `Path("")` 는 `.` 이라 `.exists()` 가 True 다 — 빈 값·비파일은 "참조 없음".
    if str(UDS_REF_SUDS_PATH or "").strip() and ref_doc_path.is_file():
        if not _ref_safety_ok:
            # 침묵 금지 — 이 문서는 **다른 프로젝트의 설계서**일 수 있다.
            _logger.warning(
                "참조 SUDS 의 프로젝트 신원을 확인하지 못했다(%s: ref=%s vs payload=%s) — "
                "ASIL·Related 는 적용하지 않는다. 서술 필드만 보강한다. "
                "이 프로젝트의 SUDS 를 쓰려면 UDS_REF_SUDS_PATH 를 지정할 것.",
                _ref_identity["reason"], _ref_identity["ref_tokens"], _ref_identity["payload_tokens"],
            )
        ref_doc = None
        try:
            ref_doc = docx.Document(str(ref_doc_path))
            ref_map = _extract_function_info_from_docx(ref_doc)
        except Exception:
            ref_map = {}
        finally:
            # (R47-j N27-b) 여기서 쓰는 건 `ref_map` 뿐이다. 이 지역변수는 함수 끝까지 살아 정본(실측 50MB docx)의
            #   DOM 을 빌드 내내 붙들었다 — 아래에서 같은 파일을 템플릿으로 한 번 더 여니 두 벌이 상주한다.
            #   (리뷰 I3) 추출이 던져도 놓아야 하므로 finally 다.
            del ref_doc
        if ref_map:
            patched_called = 0
            patched_calling = 0
            patched_limit = 9999
            # (R51 N40) 매칭은 이름으로 — 옛 "ID 먼저" 는 정본 번호와 생성 번호가 무관해 773 블록을 엉뚱한 함수에 실었다
            #   (`_resolve_reference_target` docstring). 같은 이름 블록 목록을 먼저 만들어 중복(정본이 한 함수를 두 절에)을 가른다.
            _ref_blocks_by_name: Dict[str, List[str]] = {}
            for _rfid, _rblk in ref_map.items():
                _rn = _normalize_symbol_name(str(_rblk.get("name") or "")).lower() if isinstance(_rblk, dict) else ""
                if _rn:
                    _ref_blocks_by_name.setdefault(_rn, []).append(_rfid)
            _seen_dup_names: Set[str] = set()
            for fid, block in ref_map.items():
                if not isinstance(block, dict):
                    continue
                target, _blocked_axes = _resolve_reference_target(
                    fid, block, function_details, function_details_by_name, _ref_blocks_by_name, ref_map,
                    _ref_stats["matching"], _seen_dup_names,
                )
                if not isinstance(target, dict):
                    continue
                bname = _normalize_symbol_name(str(block.get("name") or "")).lower()
                brel = str(block.get("related") or "").strip()
                # ref_related_by_name 도 안전축(Related ID)이다 — 신원 미확인이면 채우지 않는다.
                if bname and brel and _ref_safety_ok and "related" not in _blocked_axes:
                    ref_related_by_name[bname] = brel
                for key in ["description", "asil", "related", "precondition", "logic"]:
                    if key in _blocked_axes:
                        continue      # (R51 리뷰 W3) 같은 이름 블록끼리 갈린 축 — 이 축만 싣지 않는다
                    cur = str(target.get(key) or "").strip()
                    incoming = str(block.get(key) or "").strip()
                    if not incoming:
                        continue
                    if key == "description":
                        if (not cur) or cur.startswith("Auto-generated from"):
                            target[key] = incoming
                            target["description_source"] = "reference"
                            _ref_stats["descriptive_fields_applied"] += 1
                    elif key in {"asil", "related"}:
                        # ── 안전·추적성 축 ──
                        # ASIL 과 Related ID 는 ISO 26262 판정의 권위 필드다. 다른 프로젝트
                        # 문서에서 이름만 겹쳐 흘러들면 남의 요구 ID 추적이나 등급 오염이
                        # 된다. 신원이 확인된 경우에만 적용한다.
                        #
                        # ⚠ 판정 **순서**가 중요하다. 예전 초안은 신원 게이트를 맨 앞에 뒀는데,
                        #   그러면 어차피 적용되지 않았을 시도까지 "차단" 으로 세어 막은 양을
                        #   부풀린다. 실측: `asil` 은 이 지점 이전에 이미 `QM`(source=default)
                        #   으로 채워져 있어 애초에 적용 대상이 아니었는데도 차단 1건으로
                        #   집계됐다. 적용 자격 → 값 유효성 → 신원 순으로 본다.
                        #
                        # (R50 N38) 여기는 **빈칸만** 채우던 자리였다. 그런데 이 앞에서 SwDS 파티션 맵(`sds`)과
                        #   모듈 상속이 먼저 채우면 정본이 채울 빈칸이 없다 — 라이브 run 2079 실측: 정본 ASIL
                        #   657→35, 함수 ASIL 변경 327건(A→QM 45). 사용자 결정(2026-09-15) "정본 SwUDS 먼저, SwDS 는 빈칸만" 에 따라
                        #   소스 주석(`comment`, c_source 권위)·정본 직독(`uds`)·자기 자신만 남기고 **덮는다**.
                        #   판정은 `provenance.reference_suds_may_override` 단일 출처. 값이 달랐으면 충돌로 센다
                        #   (설계 문서와 정본이 어긋난 함수 — 침묵하면 "정본이 곧 SwDS" 로 읽힌다).
                        _blank = (not cur) or cur in {"TBD", "N/A", "-"}
                        _prev_src = canonical_source(target.get(f"{key}_source"))
                        if not _blank and not reference_suds_may_override(_prev_src):
                            # (R50 리뷰 W1) 지켜진 출처(소스 주석 등)와 정본이 **다른 값**이면 그 사실도 센다 — "정본을 막은 건" 도
                            #   "정본이 덮은 건" 만큼 검토 가치가 있다(주석 @asil D ↔ 정본 A). 신원 확인된 정본만.
                            if _ref_safety_ok and _safety_value_key(cur, key) != _safety_value_key(incoming, key):
                                _kept = _ref_stats["safety_fields_kept_conflict"]
                                _kept[_prev_src] = int(_kept.get(_prev_src, 0)) + 1
                            continue
                        if key == "asil" and incoming.upper() not in _VALID_ASIL:
                            # 참조 파싱이 어긋나 프로토타입 문자열 등이 ASIL 로 들어오는 경우.
                            _ref_stats["invalid_asil_rejected"] += 1
                            continue
                        if not _ref_safety_ok:
                            _ref_stats["safety_fields_blocked"] += 1
                            continue
                        if _blank:
                            _ref_stats["safety_fields_blank_filled"] += 1
                        elif _safety_value_key(cur, key) == _safety_value_key(incoming, key):
                            _ref_stats["safety_fields_agreed"] += 1
                        else:
                            _ovr = _ref_stats["safety_fields_overridden"]
                            _ovr[_prev_src] = int(_ovr.get(_prev_src, 0)) + 1
                            if len(_ref_stats["safety_conflicts_sample"]) < _STAT_SAMPLE_CAP:
                                _ref_stats["safety_conflicts_sample"].append({
                                    # (리뷰 I4) 이름 폴백 매칭이면 `fid` 는 정본 쪽 키라 payload 함수 id 가 아니다 — 이름을 같이 싣는다.
                                    "id": str(target.get("id") or fid), "name": str(target.get("name") or ""), "field": key,
                                    "prev": cur[:80], "prev_source": _prev_src, "reference": incoming[:80],
                                })
                        target[key] = incoming
                        target[f"{key}_source"] = "reference"
                        _ref_stats["safety_fields_applied"] += 1
                    else:
                        if (not cur) or (key == "precondition" and cur.upper() in {"N/A", "TBD", "-"}):
                            target[key] = incoming
                            _ref_stats["descriptive_fields_applied"] += 1
                # ── 구조 축 (인터페이스 정의) ──
                # 입출력 파라미터·사용 전역·호출관계는 서술이 아니라 **시험 대상 인터페이스
                # 정의**다. UDS 의 이 칸이 그대로 SUTS 시험 케이스의 대상이 되므로, 다른
                # 프로젝트 문서에서 이름만 겹쳐 흘러들면 존재하지 않는 인터페이스를 시험하는
                # 문서가 나온다. ISO 26262 추적성(UDS↔Source)이 끊긴다.
                #
                # ⚠ 그래서 안전축과 같은 신원 게이트를 건다(2026-08-04, §6 후보 12 정책).
                #   예전엔 이 6축만 게이트 밖이었다 — `_ref_safety_ok` 가 False 여도 그대로
                #   적용됐고, 심지어 2026-08-03 까지는 **계수조차 없어** 적용량을 몰랐다.
                #
                # ⚠ 판정 순서는 위 안전축과 같다: **적용 자격 → 신원**. 신원을 먼저 보면
                #   어차피 적용되지 않았을 시도까지 "차단" 으로 세어 막은 양을 부풀린다.
                #
                # ⚠ 2026-08-04 의 "이름 조인(초안 A2) 기각" 은 **다른 프로젝트 문서**(HDPDM01 SUDS)를 참조로 두던 때의 측정이다
                #   (이름이 같은 354건 중 244건이 prototype 이 다름 = 교차 프로젝트 오염). 그 레버는 신원 게이트가 맞다.
                #   그러나 그 결론이 "ID 조인이 옳다" 는 뜻은 아니었다 — 같은 프로젝트 정본에서도 ID 는 문서 번호라 생성 번호와
                #   무관하고, 이름이 다른 함수 773 블록의 구조축이 여기로 실렸다(R51 N40, `_resolve_reference_target`).
                #   지금 매칭 키는 이름 + 신원 게이트다.
                _struct = _ref_stats["structural_fields_applied"]
                _blocked = _ref_stats["structural_fields_blocked"]

                def _apply_struct(axis: str, *, eligible: bool, value: Any) -> bool:
                    """구조 축 1개 적용. 자격이 있는데 신원이 없으면 **차단으로 계수**."""
                    if not eligible:
                        return False
                    if not _ref_safety_ok:
                        _blocked[axis] += 1
                        return False
                    target[axis] = value
                    _struct[axis] += 1
                    return True

                for _axis in ("inputs", "outputs", "globals_static", "globals_global"):
                    _apply_struct(
                        _axis,
                        eligible=bool(block.get(_axis)) and not target.get(_axis) and _axis not in _blocked_axes,
                        value=block.get(_axis),
                    )
                _cur_called = str(target.get("called") or "").strip()
                if _apply_struct(
                    "called",
                    eligible=bool(block.get("called")) and "called" not in _blocked_axes
                    and ((not _cur_called) or _cur_called.upper() in {"N/A", "TBD", "-"})
                    and patched_called < patched_limit,
                    value=block.get("called"),
                ):
                    patched_called += 1
                _cur_calling = str(target.get("calling") or "").strip()
                if _apply_struct(
                    "calling",
                    eligible=bool(block.get("calling")) and "calling" not in _blocked_axes
                    and ((not _cur_calling) or _cur_calling.upper() in {"N/A", "TBD", "-"})
                    and patched_calling < patched_limit,
                    value=block.get("calling"),
                ):
                    patched_calling += 1

    # (R50 리뷰 C1) 모듈 상속은 정본 채움 **뒤** — 정본이 고친 값이 씨앗이 되고, 씨앗 출처별 건수를 남긴다(정본이 못 닿는
    #   형제 함수가 어떤 근거의 등급을 물려받았는지 검토자가 볼 수 있게).
    _ref_stats["module_inherit_by_seed_source"] = _inherit_module_asil(function_details, fn_module_map)

    if isinstance(function_details, dict) and isinstance(function_details_by_name, dict):
        for fid, info in function_details.items():
            if not isinstance(info, dict):
                continue
            name = str(info.get("name") or "").strip().lower()
            target = function_details_by_name.get(name)
            if not isinstance(target, dict):
                continue
            for src_key in ("asil", "asil_source", "related", "related_source",
                            "description", "description_source"):
                val = info.get(src_key)
                if val and (not target.get(src_key)
                            or (src_key.endswith("_source") and is_weak_source(target.get(src_key)))):
                    target[src_key] = val
            for g_key in ("globals_global", "globals_static"):
                src_g = info.get(g_key)
                tgt_g = target.get(g_key)
                if isinstance(src_g, list) and src_g and (not tgt_g or (isinstance(tgt_g, list) and not tgt_g)):
                    target[g_key] = list(src_g)

    # ── 호출 그래프 기반 Related ID 전파 (2-hop BFS) ──
    _pre_prop_has_related = sum(1 for v in (function_details or {}).values()
        if isinstance(v, dict)
        and str(v.get("related") or "").strip()
        and str(v.get("related") or "").strip().upper() not in {"TBD", "N/A", "-", "NONE"})
    _logger.info("Related ID pre-propagation: %d/%d have valid related, call_map=%d keys",
                 _pre_prop_has_related, len(function_details or {}), len(call_map or {}))
    if isinstance(function_details, dict) and call_map:
        _related_propagated = 0
        _fn_name_to_fid: Dict[str, str] = {}
        for fid, info in function_details.items():
            if isinstance(info, dict):
                fname = str(info.get("name") or "").strip().lower()
                if fname:
                    _fn_name_to_fid[fname] = fid

        def _has_related(info: Dict[str, Any]) -> bool:
            rel = str(info.get("related") or "").strip()
            return bool(rel) and rel.upper() not in {"TBD", "N/A", "-", "NONE", ""}

        def _get_related(info: Dict[str, Any]) -> str:
            return str(info.get("related") or "").strip()

        for _hop in range(2):
            propagated_this_hop = 0
            for fid, info in list(function_details.items()):
                if not isinstance(info, dict) or _has_related(info):
                    continue
                fname = str(info.get("name") or "").strip().lower()
                if not fname:
                    continue
                collected_ids: List[str] = []
                callers = calling_map.get(fname, [])
                for caller_name in callers:
                    caller_fid = _fn_name_to_fid.get(caller_name.lower())
                    if not caller_fid:
                        continue
                    caller_info = function_details.get(caller_fid)
                    if isinstance(caller_info, dict) and _has_related(caller_info):
                        for rid in _get_related(caller_info).replace(";", ",").split(","):
                            rid = rid.strip()
                            if rid and rid not in collected_ids:
                                collected_ids.append(rid)
                callees = call_map.get(fname, [])
                for callee_name in callees:
                    callee_fid = _fn_name_to_fid.get(callee_name.lower())
                    if not callee_fid:
                        continue
                    callee_info = function_details.get(callee_fid)
                    if isinstance(callee_info, dict) and _has_related(callee_info):
                        for rid in _get_related(callee_info).replace(";", ",").split(","):
                            rid = rid.strip()
                            if rid and rid not in collected_ids:
                                collected_ids.append(rid)
                if collected_ids:
                    info["related"] = ", ".join(collected_ids[:8])
                    info["related_source"] = "call_graph"
                    propagated_this_hop += 1
                    if isinstance(function_details_by_name, dict):
                        tgt = function_details_by_name.get(fname)
                        if isinstance(tgt, dict):
                            tgt["related"] = info["related"]
                            tgt["related_source"] = "call_graph"
            _related_propagated += propagated_this_hop
            if propagated_this_hop == 0:
                break
        if _related_propagated > 0:
            _logger.info("Related ID propagation via call graph: %d functions updated", _related_propagated)

    ai_func_desc_enable = bool(payload.get("ai_func_desc_enable") or payload.get("ai_enable"))
    if ai_func_desc_enable and isinstance(function_details, dict):
        inference_count = sum(
            1 for v in function_details.values()
            if isinstance(v, dict) and is_weak_source(v.get("description_source"))
        )
        if inference_count > 0:
            _logger.info("AI function description: %d inference-sourced functions, starting AI generation", inference_count)
            try:
                from workflow.uds_ai import generate_ai_function_descriptions
                # body는 detail dict에 없다 — 파서가 별도 맵으로 싣는다(uds_generator
                # function_body_snippets). 안 넘기면 2차 refinement가 조용히 no-op다.
                _body_snips = payload.get("function_body_snippets")
                ai_descs = generate_ai_function_descriptions(
                    function_details,
                    module_map if isinstance(module_map, dict) else None,
                    body_snippets=_body_snips if isinstance(_body_snips, dict) else None,
                )
                if ai_descs:
                    applied = 0
                    for fid, info in function_details.items():
                        if not isinstance(info, dict):
                            continue
                        src = str(info.get("description_source") or "").strip().lower()
                        if src in {"comment", "sds", "reference"}:
                            continue
                        ai_desc = ai_descs.get(f"__fid__{fid}")
                        if not ai_desc:
                            name = str(info.get("name") or "").strip().lower()
                            ai_desc = ai_descs.get(name)
                        if ai_desc:
                            info["description"] = ai_desc
                            info["description_source"] = "ai"
                            applied += 1
                            if isinstance(function_details_by_name, dict):
                                name = str(info.get("name") or "").strip().lower()
                                target = function_details_by_name.get(name)
                                if isinstance(target, dict):
                                    target["description"] = ai_desc
                                    target["description_source"] = "ai"
                    _logger.info("AI function description: applied %d / %d", applied, inference_count)
            except Exception as e:
                _logger.warning("AI function description failed: %s", e)

    if isinstance(function_details, dict):
        for k, v in list(function_details.items()):
            if isinstance(v, dict):
                function_details[k] = _finalize_function_fields(v)
    if isinstance(function_details_by_name, dict):
        for k, v in list(function_details_by_name.items()):
            if isinstance(v, dict):
                function_details_by_name[k] = _finalize_function_fields(v)

    tbd_asil = sum(1 for v in (function_details or {}).values() if isinstance(v, dict) and str(v.get("asil") or "").strip().upper() == "TBD")
    tbd_related = sum(1 for v in (function_details or {}).values() if isinstance(v, dict) and str(v.get("related") or "").strip().upper() == "TBD")
    total_fn = len(function_details or {})
    if tbd_asil > 0 or tbd_related > 0:
        _logger.warning("UDS TBD residual: asil_tbd=%d/%d, related_tbd=%d/%d", tbd_asil, total_fn, tbd_related, total_fn)

    # 호출자가 준 것인지 config 기본값인지 구분해 통계에 남긴다 — 둘 다 `mode="template"`
    # 이라 예전엔 "이 템플릿을 누가 골랐나" 를 사후에 알 수 없었다. 반영률이 낮을 때
    # 원인이 프로젝트 템플릿 미지정인지 템플릿 자체인지 갈리는 지점이다.
    template_source = "argument" if template_path else "none"
    if not template_path:
        # Delegate to config.resolve_uds_template_path() so the admin API
        # and the generator always agree on the effective template path.
        try:
            from config import resolve_uds_template_path
            resolved = resolve_uds_template_path()
            if resolved:
                template_path = resolved
                template_source = "config_fallback"
        except Exception as exc:
            _logger.debug("UDS template fallback resolution failed: %s", exc)

    if template_path:
        template_path = str(template_path)
        module_name = (
            payload.get("module_name")
            or payload.get("module")
            or summary.get("module_name")
            or summary.get("module")
            or str(project)
        )
        reference_lines = _build_uds_reference_lines(payload)
        replacements = {
            "{{project_name}}": str(project),
            "{{PROJECT_NAME}}": str(project),
            "{{MODULE_NAME}}": str(module_name),
            # Flat-text fallback only: used if the reference-table paragraph
            # wasn't found (e.g. custom template without the token).
            "{{REFERENCE_TABLE}}": "\n".join(reference_lines) if reference_lines else "N/A",
            "{{job_url}}": str(payload.get("job_url") or ""),
            "{{build_number}}": str(payload.get("build_number") or ""),
            "{{generated_at}}": str(generated_at),
            "{{overview}}": overview,
            "{{requirements}}": requirements,
            "{{interfaces}}": interfaces,
            "{{uds_frames}}": uds_frames,
            "{{notes}}": notes,
        }
        doc = docx.Document(template_path)
        _pics = _PictureSink(doc)     # (R53 N27-c) 이 문서의 모든 그림 삽입·원본 블록 되붙임은 이 싱크를 지난다
        # 1) First, expand the reference-table token into a paragraph with
        #    real soft line breaks (w:br) so Word renders each entry on its
        #    own line. Consumes the token in-place.
        _replace_reference_table_paragraph(doc, reference_lines)
        # 2) Then run the generic flat-text substitution for the remaining
        #    single-line tokens (and as a fallback for any stray
        #    {{REFERENCE_TABLE}} paragraph we didn't catch above).
        _replace_docx_text(doc, replacements)
        # 3) 대괄호 표식(`[Project Name]`)은 `{{토큰}}` 이 아니라 위 치환이 못 잡는다.
        #    표지·Introduction 이 이 자리를 쓴다 — 두 경로 모두에 적용해야 한다.
        _n_proj = _fill_bracket_project_name(doc, str(project))
        if _n_proj:
            _logger.info("템플릿 `[Project Name]` %d곳을 %r 로 채웠다", _n_proj, str(project))
        if _template_has_placeholders(doc):
            # 토큰 치환 전용 템플릿 — SwUFn 표를 순회하지 않으므로 함수 반영률 개념이 없다.
            # 통계를 **안 남기면** 소비처가 "통계 부재 = 문제 없음" 으로 읽으므로 mode 를
            # 명시해서 남긴다(미측정과 정상을 구분).
            _ph_stats = {
                "mode": "placeholder_substitution",
                "template_path": str(template_path or ""),
                "template_source": template_source,
                "payload_functions": None,
                "matched_functions": None,
                "match_pct": None,
                "note": "토큰 치환 템플릿이라 SwUFn 함수 반영률이 적용되지 않는다(미측정).",
                # (R50 리뷰 W3) 이 모드는 본문 절을 싣는 자리 자체가 없다 — 있는 절은 전부 미배치다(템플릿 분기와 같은 키).
                "text_sections_unplaced": {
                    k: len(str(v)) for k, v in (
                        ("overview", overview), ("requirements", requirements), ("interfaces", interfaces),
                        ("uds_frames", uds_frames), ("notes", notes),
                    ) if str(v or "").strip()
                },
                # (R47-c 리뷰 W4) 참조 보강 루프는 이 분기보다 **위**에서 이미 돌았다 — 세 종결 경로 중 여기만
                #   기록을 버려 보드가 "참조 통계를 남기기 전 빌더" 라는 틀린 사유를 말했다.
                "reference_suds": _ref_stats,
            }
            _save_docx(doc, out, output_path, _ph_stats)
            return str(out)
        # 템플릿에 치환 키가 없으면, 구조만 복제하고 콘텐츠는 새로 작성
        blocks = _extract_template_blocks(doc)
        template_section_map = _extract_template_section_map(doc)
        template_section_block_map = _extract_template_section_block_map(doc)
        _clear_docx_body(doc)
        # 표지 같은 **선행 구조 블록**은 자동 목차보다 먼저 나가야 한다. 루프에만
        # 맡기면 아래 "목차 마커가 없으면 목차를 넣는다" 가 먼저 실행돼 목차 다음에
        # 표지가 오는 문서가 된다.
        _restored_blocks = 0      # 표지 등 원본 그대로 되살린 구조 블록
        _preserved_tables = 0     # 생성기가 채우지 않아 원본을 유지한 표
        _rows_recovered = 0       # 템플릿 행수였다면 잘렸을 데이터 행
        _rows_trimmed = 0         # 템플릿 행수였다면 남았을 빈 행
        _unattributed_swcoms: Set[str] = set()   # 전역변수를 귀속시키지 못한 컴포넌트
        _lead_raw = 0
        while _lead_raw < len(blocks) and blocks[_lead_raw][0] == "raw":
            try:
                _append_body_block(doc, blocks[_lead_raw][1], picture_sink=_pics)
                _restored_blocks += 1
            except Exception:   # noqa: BLE001 - 표지 복원 실패가 생성을 막지는 않는다
                _logger.warning("표지 블록 복원 실패 — 표지 없이 계속한다", exc_info=True)
            _lead_raw += 1
        has_contents_marker = False
        skip_table_idx = -1
        for kind, block in blocks:
            if kind == "heading" and str(block[1]).strip().lower() == "contents":
                has_contents_marker = True
                break
            if kind == "para" and str(block.get("text") or "").strip().lower() == "contents":
                has_contents_marker = True
                break
        toc_inserted = False
        if not has_contents_marker:
            doc.add_heading("Contents", level=2)
            _add_docx_toc(doc)
            toc_inserted = True
        heading_stack: List[str] = []
        module_funcs: Dict[str, Dict[str, List[str]]] = {}
        interface_queue: List[Dict[str, Any]] = []
        internal_queue: List[Dict[str, Any]] = []
        function_info_template: Optional[Tuple[int, int, Any, Optional[List[List[str]]]]] = None
        for kind_t, payload_t in blocks:
            if kind_t != "table":
                continue
            rows_t, cols_t, style_t, header_rows_t, _ctx_titles_t, _el_t = payload_t
            if header_rows_t:
                header_texts = [str(c or "").strip() for row in header_rows_t for c in row]
                if any("Function Information" in c for c in header_texts):
                    function_info_template = (rows_t, cols_t, style_t, header_rows_t)
                    break
        # ⚠ 여기 있던 `swufn_table_spec` 은 **도달 불가 중복**이라 지웠다.
        #   빌드 정규식이 `r"(swufn_\\d+)"` — raw string 안의 `\\` 는 리터럴 백슬래시라
        #   heading 제목에 결코 매치되지 않아 dict 는 항상 비었고, 조회부(아래
        #   `target_idx` 분기 바로 위)도 같은 죽은 정규식을 써서 한 번도 적중하지 못했다.
        #   살아 있는 경로는 `target_idx` 전방탐색이고, **같은 표를 같은 방식으로 찾는다**.
        #   실측(tokenized 템플릿·정본 SUDS 양쪽, gate 통과 heading 429개):
        #   두 경로의 (rows, cols, style) 이 **429/429 동일**했다.
        #   → 고쳐서 되살리면 한 번도 돈 적 없는 코드를 켜는 것이고 얻는 게 없다.
        for row in function_table_rows:
            if len(row) < 5:
                continue
            swcom = str(row[0] or "").strip()
            name = str(row[3] or "").strip()
            ftype = str(row[4] or "").strip().lower()
            if not swcom or not name:
                continue
            entry = module_funcs.setdefault(swcom, {"interfaces": [], "internals": []})
            if "i/f" in ftype or "if" == ftype:
                entry["interfaces"].append(name)
            else:
                entry["internals"].append(name)
            info = None
            if isinstance(function_details, dict):
                info = function_details.get(str(row[2] or "").strip())
            if not isinstance(info, dict) and isinstance(function_details_by_name, dict):
                info = function_details_by_name.get(name.lower())
            if isinstance(info, dict):
                if "i/f" in ftype or "if" == ftype:
                    interface_queue.append(info)
                else:
                    internal_queue.append(info)
        swcom_functions: Dict[str, List[str]] = {}
        swcom_function_files: Dict[str, Set[str]] = {}
        swcom_global_hints: Dict[str, Set[str]] = {}
        if isinstance(function_table_rows, list):
            for row in function_table_rows:
                if not isinstance(row, list) or len(row) < 4:
                    continue
                swcom = str(row[0] or "").strip()
                fn_name = str(row[3] or "").strip()
                if not swcom or not fn_name:
                    continue
                swcom_functions.setdefault(swcom, []).append(fn_name)
                f_info = function_details_by_name.get(fn_name.lower()) if isinstance(function_details_by_name, dict) else None
                if isinstance(f_info, dict):
                    fpath = str(f_info.get("file") or "").strip()
                    if fpath:
                        swcom_function_files.setdefault(swcom, set()).add(str(Path(fpath).name).lower())
                    for key_g in ["globals_global", "globals_static"]:
                        for g in f_info.get(key_g) or []:
                            raw = str(g or "").strip()
                            if not raw:
                                continue
                            mtag = re.match(r"^\[(?:INOUT|IN|OUT)\]\s+(.+)$", raw)
                            base = mtag.group(1).strip() if mtag else raw
                            name0 = re.split(r"(?:->|\.)", base)[0].strip()
                            if name0:
                                swcom_global_hints.setdefault(swcom, set()).add(name0)

        def _current_swcom_id() -> str:
            for h in reversed(heading_stack):
                m = re.search(r"\b(SwCom_\d+)\b", str(h), flags=re.I)
                if m:
                    return m.group(1).replace("swcom", "SwCom")
            return ""

        def _current_swcom_label() -> str:
            for h in reversed(heading_stack):
                m = re.search(r"\bSwCom_\d+\s*\(([^)]+)\)", str(h), flags=re.I)
                if m:
                    return str(m.group(1) or "").strip()
            return ""

        def _is_register_alias(name: str) -> bool:
            return bool(re.match(r"^REG_[A-Z0-9_]+$", str(name or "").strip()))

        def _norm_stem(name: str) -> str:
            s = re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
            for suffix in ["itpds", "pds", "it", "main"]:
                if s.endswith(suffix) and len(s) > len(suffix) + 2:
                    s = s[: -len(suffix)]
            return s

        def _filter_global_names_by_swcom(
            all_names: List[str],
            swcom_id: str,
            module_label: str = "",
            static_only: Optional[bool] = None,
        ) -> List[str]:
            names = [str(n).strip() for n in all_names if str(n).strip() and not _is_register_alias(str(n))]
            if not swcom_id:
                swcom_id = ""
            module_candidates: Set[str] = set()
            label_norm = re.sub(r"[^a-z0-9]+", "", str(module_label or "").lower())
            if label_norm:
                module_candidates.add(label_norm)
                module_candidates.add(label_norm.replace("system", "sys"))
                if "system" in label_norm and "os" in label_norm:
                    module_candidates.add("sysos")
            # 1) module label matching has priority over swcom_id mapping
            selected: List[str] = []
            if module_candidates:
                for n in names:
                    info_g = globals_info_map.get(n, {}) if isinstance(globals_info_map, dict) else {}
                    is_static = str(info_g.get("static") or "").strip().lower() == "true"
                    if static_only is True and not is_static:
                        continue
                    if static_only is False and is_static:
                        continue
                    gfile_l = str(info_g.get("file") or "").lower()
                    gblob = re.sub(r"[^a-z0-9]+", "", gfile_l)
                    if any(tok and tok in gblob for tok in module_candidates):
                        selected.append(n)
                if selected:
                    return list(dict.fromkeys(selected))
            hints = swcom_global_hints.get(swcom_id, set())
            for n in names:
                info_g = globals_info_map.get(n, {}) if isinstance(globals_info_map, dict) else {}
                is_static = str(info_g.get("static") or "").strip().lower() == "true"
                if static_only is True and not is_static:
                    continue
                if static_only is False and is_static:
                    continue
                if n in hints:
                    selected.append(n)
            if selected:
                return list(dict.fromkeys(selected))
            file_names = swcom_function_files.get(swcom_id, set())
            if not file_names:
                # ⚠ 여기서 `names`(**전체**)를 돌려주면 귀속에 실패한 컴포넌트 표에
                #   이 프로젝트 전역변수가 통째로 실린다. `swcom_function_files` 는
                #   **payload 의** function_table_rows 로만 만들어지므로, 템플릿이
                #   payload 보다 넓으면(정본이 늘 그렇다) 대부분의 컴포넌트가 여기로
                #   온다. 실측(KJPDS02_PV 정본, payload 는 SwCom_01 뿐): 컴포넌트별
                #   전역/정적 표 64개 중 43개가 366개를 통째로 받았고, 그게 템플릿
                #   행수(2~5행)에 잘려 **1~4개만** 남는 바람에 "그 컴포넌트의 전역
                #   변수" 처럼 보였다. 표 크기를 데이터에 맞추자 8,562행으로 드러났다.
                # ⚠ 문서 레벨 표(`swcom_id` 없음)는 전체가 맞다 — 실측: 표준 템플릿의
                #   전역/정적 표 4개는 **전부** 문서 레벨, 정본의 64개는 **전부**
                #   SwCom 아래다. 그래서 두 경우를 갈라야 한다.
                if not swcom_id:
                    return names
                _unattributed_swcoms.add(swcom_id)
                return []
            file_stems = {_norm_stem(Path(x).stem) for x in file_names}
            for n in names:
                info_g = globals_info_map.get(n, {}) if isinstance(globals_info_map, dict) else {}
                is_static = str(info_g.get("static") or "").strip().lower() == "true"
                if static_only is True and not is_static:
                    continue
                if static_only is False and is_static:
                    continue
                gfile = str(info_g.get("file") or "").strip()
                gstem = _norm_stem(Path(gfile).stem) if gfile else ""
                if gstem and any(gstem == fs or gstem.startswith(fs) or fs.startswith(gstem) for fs in file_stems):
                    selected.append(n)
            return list(dict.fromkeys(selected))

        def _filter_rows_by_swcom(rows_in: List[List[str]], swcom_id: str, module_label: str = "") -> List[List[str]]:
            if not swcom_id or not isinstance(rows_in, list):
                swcom_id = swcom_id or ""
            if not isinstance(rows_in, list):
                return rows_in
            hints = swcom_global_hints.get(swcom_id, set())
            if not hints and module_label:
                label_blob = re.sub(r"[^a-z0-9]+", "", module_label.lower())
                if "system" in label_blob and "os" in label_blob:
                    hints = {"u8g_SystemTm_5ms", "u8g_SystemTm_10ms", "u8g_SystemTm_50ms", "u8s_InitiComplet_F"}
            if not hints:
                return []
            out_rows: List[List[str]] = []
            for row in rows_in:
                if not isinstance(row, list) or not row:
                    continue
                blob = " ".join([str(x or "") for x in row])
                if any(re.search(rf"\b{re.escape(h)}\b", blob) for h in hints):
                    out_rows.append(row)
            return out_rows

        callers_map: Dict[str, List[str]] = {}
        if isinstance(call_map, dict):
            for caller_name, callees in call_map.items():
                cname = _normalize_symbol_name(str(caller_name or "")).lower()
                if not cname or not isinstance(callees, list):
                    continue
                for callee in callees:
                    callee_name = _normalize_symbol_name(str(callee or "")).lower()
                    if not callee_name:
                        continue
                    callers_map.setdefault(callee_name, []).append(cname)
        for k, vals in list(callers_map.items()):
            dedup: List[str] = []
            for v in vals:
                if v not in dedup:
                    dedup.append(v)
            callers_map[k] = dedup

        def _next_block_kind(blocks_list, start_idx: int) -> str:
            for j in range(start_idx + 1, len(blocks_list)):
                kind_j, payload_j = blocks_list[j]
                if kind_j == "raw":
                    # 표지 같은 구조 블록은 "다음에 오는 것" 판정 대상이 아니다.
                    continue
                if kind_j == "para":
                    text_j = str(payload_j.get("text") or "").strip()
                    if not text_j:
                        continue
                return kind_j
            return ""
        def _section_has_table(blocks_list, start_idx: int, current_level: int) -> bool:
            for j in range(start_idx + 1, len(blocks_list)):
                kind_j, payload_j = blocks_list[j]
                if kind_j == "heading":
                    level_j = 1
                    try:
                        level_j = int(payload_j[0])
                    except Exception:
                        level_j = 1
                    if level_j <= current_level:
                        return False
                    continue
                if kind_j == "table":
                    return True
                if kind_j == "para":
                    text_j = str(payload_j.get("text") or "").strip()
                    if text_j:
                        continue
            return False

        section_note_map = {
            "parameter definition": template_section_map.get("parameter definition", ""),
            "version information": template_section_map.get("version information", ""),
        }
        note_added: set[str] = set()

        # ── 생성 충실도 계측 ───────────────────────────────────────────────────
        # 이 라이터는 템플릿 heading 을 순회하므로 **payload 함수 ↔ 문서 반영**이 1:1 이
        # 아니다. 예전엔 그 격차가 어디에도 안 남아, 22.0% 가 미반영인 문서가
        # "성공" 으로 기록됐다. resolver 는 heading 만으로 빈 껍데기를 합성하는 폴백이
        # 여럿이라 **호출 결과를 실제로 분류**해야 한다(선언적 집합 차집합은 퍼지 매칭을
        # 과소 계상해 거짓 경고를 낸다).
        # 템플릿이 **삭제된 함수**로 표시한 heading 은 비어 있는 게 정상이다 — 갭으로 세면
        # 오탐이 된다.
        #
        # ⚠ 이 마커는 이제 **계측만이 아니라 산출**을 가른다. `unmatched_headings=drop`
        #   에서 `deleted` 는 남고 `empty` 는 지워지므로, 어휘를 놓치면 **의도해서 비운
        #   자리가 문서에서 사라진다**. 그래서 어휘를 짐작하지 않고 전수 조사했다
        #   (2026-09-01, 실문서 4종 · SwUFn heading **2,505개**):
        #
        #     HDPDM01 정본 v1.07   429개 → (New) 47 · (NEW) 10 · (삭제) 9 ·
        #                                  (Interface -> Internal 이동) 4 ·
        #                                  (Internal -> Interface 이동) 2 · (New, 삭제) 1
        #     HDPDM01 템플릿        429개 → 〃 (정본과 동일)
        #     KJPDS02 dv_SwUDS      631개 → (New) 1 · (삭제) 1
        #     swuds_v2.08         1,016개 → (new) 1
        #
        #   괄호 주석 자체가 드물고(2,505 중 147), 삭제 계열은 **11건 전부** 이 정규식에
        #   걸린다. `이동` 은 삭제가 아니다 — 함수는 다른 절에 살아 있으므로 payload 에
        #   있으면 그쪽에서 반영되고, 없으면 다른 미반영 heading 과 같은 처지다.
        #   → 어휘를 넓히지 않는다. 넓히면 실측 근거 없이 `drop` 의 예외만 늘어난다.
        #   다른 어휘를 쓰는 정본이 나오면 **그 문서를 세어 보고** 여기 추가할 것.
        _deleted_marker = re.compile(r"\([^)]*(?:삭제|제거|delete[d]?)[^)]*\)", re.I)

        _payload_fn_names: Set[str] = set()
        for _src in (function_details, function_details_by_name):
            if isinstance(_src, dict):
                for _v in _src.values():
                    if isinstance(_v, dict) and _v.get("name"):
                        _payload_fn_names.add(
                            _normalize_symbol_name(str(_v.get("name"))).lower())
        _matched_fn_names: Set[str] = set()
        # (R50 N38) 본문 절(overview/requirements/interfaces/uds_frames/notes)이 템플릿 heading 에 **실린** 키.
        #   정본 레이아웃엔 `Requirements` 가 없어 SwRS 79,572자가 조용히 빠졌다(run 2078) — 어디에도 계수가 없었다.
        _text_sections_placed: Set[str] = set()
        _empty_headings: List[str] = []
        _deleted_headings: List[str] = []
        _boilerplate_headings: List[str] = []
        # 지운 것과 비워 둔 것은 **다른 사실**이다 — 한 칸에 합치면 산출물을 설명 못 한다.
        _dropped_headings: List[str] = []
        _unmatched_mode, _unmatched_bad = normalize_unmatched_headings(
            payload.get("unmatched_headings"))
        if _unmatched_bad:
            _logger.warning(
                "unmatched_headings=%r 를 알 수 없어 기본값(%s)으로 진행한다",
                _unmatched_bad, UNMATCHED_HEADINGS_KEEP)
        _drop_unmatched = _unmatched_mode == UNMATCHED_HEADINGS_DROP
        # >0 이면 그 레벨 이하의 heading 을 만날 때까지 **절 전체**를 버린다.
        # heading 만 지우고 본문을 남기면 내용이 엉뚱한 절에 붙는다.
        _drop_until_level = 0

        def _fn_match_kind(title_text: str, info: Any) -> str:
            """heading 하나의 분류 — ``matched`` | ``deleted`` | ``boilerplate`` | ``empty``.

            ⚠ 판정을 **여기 하나에만** 둔다. 아래 `_note_fn_match`(계측)와 본문 루프의
              "지울 것인가"(산출)가 같은 규칙을 봐야 한다 — 규칙이 갈리면 세는 것과
              지우는 것이 서로 다른 집합이 되고, 그러면 수치가 산출물을 설명하지 못한다.
            """
            name = ""
            if isinstance(info, dict):
                name = _normalize_symbol_name(str(info.get("name") or "")).lower()
            # `_finalize_function_fields` 가 만들지 **않는** 필드들 — 있으면 진짜 내용이다.
            has_hard_content = isinstance(info, dict) and any(
                info.get(k) for k in ("prototype", "inputs", "outputs", "logic")
            )
            known = bool(name) and name in _payload_fn_names
            if known and has_hard_content:
                return "matched"
            if _deleted_marker.search(str(title_text)):
                return "deleted"
            if known:
                return "boilerplate"
            return "empty"

        def _note_fn_match(title_text: str, info: Any) -> None:
            """heading 하나가 payload 로 채워졌는지 vs 빈 껍데기인지 분류.

            세 축으로 나눈다 — 섞으면 수치가 부풀거나 경고가 오탐이 된다:
              · **반영**      : payload 의 실제 내용이 표에 들어갔다
              · **합성만**    : 이름만 맞고 내용은 생성기가 만든 보일러플레이트다
              · **의도된 빈칸**: 템플릿이 "삭제" 로 표기한 heading
              · 나머지        : 실제 갭

            ⚠ 합성을 분리하는 이유(실측): `_finalize_function_fields` 는 내용이 **완전히 빈**
            함수에도 `description="alpha은(는) alpha 관련 연산을 수행하고…"`, `asil="QM"`,
            `related="TBD"` 를 채운다. 그걸 "반영" 으로 세면 내용 0인 함수가 반영률을 올린다.

            ⚠ **description 축은 이 지표에서 제외한다.** 합성 여부를 판별할 수단이 둘 다 못
            쓴다: ①`description_source` 는 `_resolve_related_asil_desc` 가 **출처 미기록을 전부
            `"inference"` 로 확정**해 사람이 쓴 설명까지 그 값이 된다(실측 확인 — 별도 결함)
            ②`_is_generic_description` 은 합성기 자신의 출력(`…관련 연산을 수행하고…`)을
            generic 으로 보지 않는다. 고장난 판정을 지표에서 흉내내면 결함이 복제되므로
            **생성기가 만들지 않는 필드만** 근거로 삼는다. 그 결과 설명만 있고
            prototype/inputs/outputs/logic 이 전무한 함수는 갭으로 잡히는데, 단위 상세 설계
            문서 기준으로는 그게 맞다.
            """
            kind = _fn_match_kind(title_text, info)
            if kind == "matched":
                _matched_fn_names.add(
                    _normalize_symbol_name(str((info or {}).get("name") or "")).lower())
            elif kind == "deleted":
                _deleted_headings.append(str(title_text)[:200])
            elif kind == "boilerplate":
                # 이름은 payload 에 있는데 내용이 전부 합성이다 — 갭이지만 원인이 다르다.
                _boilerplate_headings.append(str(title_text)[:200])
            else:
                _empty_headings.append(str(title_text)[:200])

        def _resolve_function_info(title_text: str, key_text: str) -> Dict[str, Any]:
            info: Optional[Dict[str, Any]] = None
            heading_fn_name = ""
            if ":" in str(title_text):
                heading_fn_name = _normalize_symbol_name(str(title_text).split(":", 1)[1]).lower()
            # For explicit SwUFn headings, prioritize function-name matching over ID.
            # Template SwUFn IDs may differ from parsed source IDs by module ordering.
            if ":" in str(title_text):
                fn_name = heading_fn_name
                if isinstance(function_details_by_name, dict):
                    info = function_details_by_name.get(fn_name)
            if not isinstance(info, dict) and ":" in str(title_text):
                fn_name = heading_fn_name
                if isinstance(function_details, dict) and fn_name:
                    for cand in function_details.values():
                        if not isinstance(cand, dict):
                            continue
                        cand_name = _normalize_symbol_name(str(cand.get("name") or "")).lower()
                        if cand_name == fn_name:
                            info = cand
                            break
                        # tolerate wrapper prefixes/suffixes while avoiding unrelated fallback.
                        if cand_name.endswith(fn_name) or fn_name.endswith(cand_name):
                            info = cand
                            break
            fn_id = re.search(r"(swufn_\d+)", key_text, re.I)
            # Important: for explicit SwUFn headings, do NOT fallback by ID.
            # Template SwUFn IDs can diverge from parsed source order and cause wrong function mapping.
            if (not heading_fn_name) and (not isinstance(info, dict)) and fn_id and isinstance(function_details, dict):
                info = function_details.get(fn_id.group(1).upper())
            if not isinstance(info, dict) and ":" in str(title_text):
                fn_name = heading_fn_name
                if fn_name:
                    sig = ""
                    for ln in (interface_functions or "").splitlines() + (internal_functions or "").splitlines():
                        ln = str(ln).strip()
                        if re.search(rf"\b{re.escape(fn_name)}\s*\(", ln, flags=re.I):
                            sig = ln
                            break
                    if sig:
                        info = {
                            "id": "",
                            "name": fn_name,
                            "prototype": sig,
                            "description": "",
                            "asil": "",
                            "related": "",
                            "inputs": _parse_signature_params(sig),
                            "outputs": _parse_signature_outputs(sig, fn_name),
                            "precondition": "",
                            "globals_global": [],
                            "globals_static": [],
                            "called": "",
                            "logic": "",
                        }
            # For explicit SwUFn headings, never consume queue fallback.
            # Queue fallback can incorrectly map another module function (e.g., Lib -> SwCom_01 main).
            if not isinstance(info, dict) and not heading_fn_name:
                ctx = " ".join([str(h).lower() for h in heading_stack])
                if "interface functions" in ctx and interface_queue:
                    info = interface_queue.pop(0)
                elif "internal functions" in ctx and internal_queue:
                    info = internal_queue.pop(0)
            if not isinstance(info, dict) and not heading_fn_name:
                info = {
                    "id": _normalize_swufn_id(str(fn_id.group(1)) if fn_id else ""),
                    "name": str(title_text).split(":", 1)[1].strip() if ":" in str(title_text) else str(title_text),
                    "prototype": "",
                    "description": "",
                    "asil": "",
                    "related": "",
                    "inputs": [],
                    "outputs": [],
                    "precondition": "",
                    "globals_global": [],
                    "globals_static": [],
                    "called": "",
                    "logic": "",
                }
            if not isinstance(info, dict) and heading_fn_name:
                called_text = ""
                if isinstance(call_map, dict):
                    target_norm = _normalize_symbol_name(str(heading_fn_name or "")).lower()
                    target_compact = re.sub(r"[^a-z0-9_]", "", target_norm)
                    for k, vals in call_map.items():
                        key_norm = _normalize_symbol_name(str(k or "")).lower()
                        key_compact = re.sub(r"[^a-z0-9_]", "", key_norm)
                        if not (
                            key_norm == heading_fn_name
                            or key_norm == target_norm
                            or (target_compact and key_compact == target_compact)
                        ):
                            continue
                        called_text = ", ".join([str(v) for v in (vals or []) if v])
                        break
                info = {
                    "id": _normalize_swufn_id(str(fn_id.group(1)) if fn_id else ""),
                    "name": heading_fn_name,
                    "prototype": "",
                    "description": _fallback_function_description(heading_fn_name, called_text),
                    "asil": "",
                    "related": "",
                    "inputs": [],
                    "outputs": [],
                    "precondition": "",
                    "globals_global": [],
                    "globals_static": [],
                    "called": called_text,
                    "logic": "",
                }
            if isinstance(info, dict) and heading_fn_name:
                if fn_id:
                    info["id"] = _normalize_swufn_id(str(fn_id.group(1)))
                if not str(info.get("prototype") or "").strip() and heading_fn_name == "main":
                    info["prototype"] = "void main( void )"
                if not str(info.get("description") or "").strip():
                    info["description"] = _fallback_function_description(
                        heading_fn_name,
                        info.get("called") or info.get("calls_list") or [],
                    )
                if not str(info.get("calling") or "").strip():
                    callers = callers_map.get(heading_fn_name, [])
                    lines: List[str] = []
                    for c in callers:
                        sig = ""
                        if isinstance(function_details_by_name, dict):
                            cinfo = function_details_by_name.get(str(c).lower())
                            if isinstance(cinfo, dict):
                                sig = str(cinfo.get("prototype") or "").strip()
                        lines.append(sig or str(c))
                    info["calling"] = "\n".join([ln for ln in lines if ln])
                ref_rel = ref_related_by_name.get(heading_fn_name)
                # (R52 N39) `main` 특례를 지웠다 — 다른 함수와 같은 규칙. 예전엔 정본에 main 이 없으면 프로젝트 ID 리터럴
                #   ("SwST_01, SwCom_01, SwSTR_…")을 `rule` 로 실었다: 그 값은 KJPDS02 정본 main 의 Related 이자
                #   `docs/uds_function_swcom_override.json` 의 main 항목과 같은 값이라 코드에 둘 이유가 없고, 다른
                #   프로젝트에선 지어내기다(같은 리터럴이 이 파일 3곳 + `function_analyzer.py` 2곳에 있었다).
                cur_related = str(info.get("related") or "").strip()
                if cur_related in {"", "TBD", "SwCom_01"} and ref_rel:
                    info["related"] = ref_rel
                    info["related_source"] = "reference"
            return info

        def _build_function_info_table(info: Dict[str, Any], cols: int, style: Any):
            fn_key = str(info.get("name") or "").strip().lower()
            callee_names = [str(c).strip() for c in (info.get("calls_list") or []) if str(c).strip()]
            if (not callee_names) and call_relation_mode == "code" and isinstance(call_map, dict):
                fn_norm = _normalize_symbol_name(str(info.get("name") or "")).lower()
                if fn_norm:
                    recovered: List[str] = []
                    for ck, vals in call_map.items():
                        if _normalize_symbol_name(str(ck or "")).lower() != fn_norm:
                            continue
                        if isinstance(vals, list):
                            recovered.extend([str(x).strip() for x in vals if str(x).strip()])
                    if recovered:
                        callee_names = list(dict.fromkeys(recovered))
            # Do not recover callee from existing "called" text.
            # Template/reference merge may inject caller-oriented text and
            # corrupt directionality for leaf functions.
            callee_names = list(dict.fromkeys(callee_names))
            caller_names = list(dict.fromkeys(callers_map.get(fn_key, [])))

            def _sig_lines(names: List[str]) -> List[str]:
                out: List[str] = []
                for nm in names:
                    sig = ""
                    cinfo = function_details_by_name.get(str(nm).lower()) if isinstance(function_details_by_name, dict) else None
                    if isinstance(cinfo, dict):
                        sig = str(cinfo.get("prototype") or "").strip()
                    out.append(sig or str(nm))
                return [x for x in out if x]

            callee_lines = _sig_lines(callee_names)
            caller_lines = _sig_lines(caller_names)
            if fn_key == "wake_up_setting":
                callee_name_set = {
                    str(x).strip().lower()
                    for x in _extract_call_names("\n".join(callee_lines))
                    if str(x).strip()
                }
                if (
                    "l_ifc_init" not in callee_name_set
                    and {"l_sys_init", "monitor_adc_enable", "monitor_adc_init"} & callee_name_set
                ):
                    l_ifc_sig = ""
                    cinfo = function_details_by_name.get("l_ifc_init") if isinstance(function_details_by_name, dict) else None
                    if isinstance(cinfo, dict):
                        l_ifc_sig = str(cinfo.get("prototype") or "").strip()
                    callee_lines = ([l_ifc_sig or "l_ifc_init"] + callee_lines)
                    dedup_lines: List[str] = []
                    for ln in callee_lines:
                        if ln and ln not in dedup_lines:
                            dedup_lines.append(ln)
                    callee_lines = dedup_lines
            if fn_key == "main" and not caller_lines:
                caller_lines = ["void _Startup(void)"]
            # Keep canonical relation direction in persisted fields:
            # called = callees, calling = callers.
            info["called"] = "\n".join(callee_lines) if callee_lines else "N/A"
            info["calling"] = "\n".join(caller_lines) if caller_lines else "N/A"
            if fn_key == "wake_up_setting":
                current_calling = str(info.get("calling") or "")
                parsed_names = {
                    str(x).strip().lower()
                    for x in _extract_call_names(current_calling)
                    if str(x).strip()
                }
                if (
                    "l_ifc_init" not in parsed_names
                    and {"l_sys_init", "monitor_adc_enable", "monitor_adc_init"} & parsed_names
                ):
                    lines_now = [ln for ln in current_calling.splitlines() if ln.strip()]
                    lines_now.insert(0, "l_ifc_init")
                    dedup_lines: List[str] = []
                    for ln in lines_now:
                        clean = str(ln).strip()
                        if clean and clean not in dedup_lines:
                            dedup_lines.append(clean)
                    info["calling"] = "\n".join(dedup_lines) if dedup_lines else current_calling

            def _format_globals(items: List[str]) -> List[str]:
                out: List[str] = []
                for name in items:
                    raw = str(name or "").strip()
                    tag = ""
                    base = raw
                    m = re.match(r"^\[(INOUT|IN|OUT)\]\s+(.+)$", raw)
                    if m:
                        tag = m.group(1)
                        base = m.group(2).strip()
                    lookup = re.split(r"(?:->|\.)", base)[0].strip()
                    display_name = f"[{tag}] {base}" if tag else base
                    info_map = globals_info_map.get(lookup, {})
                    if globals_format_with_labels:
                        mapping = {
                            "Name": f"Name={display_name}",
                            "Type": f"Type={info_map.get('type','')}",
                            "File": f"File={Path(info_map.get('file','')).name}" if info_map.get("file") else "File=",
                            "Range": f"Range={info_map.get('range','')}",
                        }
                        parts = [mapping.get(k, "") for k in globals_format_order]
                        out.append(globals_format_sep.join([p for p in parts if p]))
                    else:
                        mapping = {
                            "Name": display_name,
                            "Type": info_map.get("type", ""),
                            "File": Path(info_map.get("file", "")).name if info_map.get("file") else "",
                            "Range": info_map.get("range", ""),
                        }
                        parts = [mapping.get(k, "") for k in globals_format_order]
                        out.append(globals_format_sep.join([p for p in parts if p]))
                return out
            # ⚠ 파라미터 그리드는 전역이 **표시 문자열로 납작해지기 전에** 뽑는다.
            #   `_format_globals` 가 지나가면 `Name=… | Type=… | Range=…` 한 줄이 되어
            #   타입·범위·초기값이 구조로는 사라진다.
            _grid_in, _grid_out = resolve_param_grid_entries(
                info, globals_info_map, struct_member_types)
            info["globals_global"] = _format_globals(info.get("globals_global") or [])
            info["globals_static"] = _format_globals(info.get("globals_static") or [])
            info_for_rows = dict(info)
            info_for_rows["_param_grid_inputs"] = _grid_in
            info_for_rows["_param_grid_outputs"] = _grid_out
            if payload.get("show_mapping_evidence"):
                info_for_rows["show_mapping_evidence"] = True
            data_rows = _build_function_info_layout(info_for_rows, cols)
            calls_list = list(dict.fromkeys(callee_names))
            if not calls_list:
                calls_list = _extract_call_names(str(info.get("called") or ""))
            logic_key = str(info.get("id") or "").strip()
            if not logic_key:
                logic_key = str(info.get("name") or "function").strip()
            logic_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", logic_key).strip("_")
            if not logic_key:
                logic_key = f"function_{abs(hash(str(info)))%100000}"
            logic_flow = info.get("logic_flow") or []
            logic_img_path = Path(out).parent / "logic" / f"{logic_key}.png"
            logic_img = None
            # 캐싱: 이미지가 이미 존재하면 재생성 건너뛰기
            if logic_img_path.exists() and logic_img_path.stat().st_size > 100:
                logic_img = str(logic_img_path)
            elif logic_flow:
                logic_img = _render_logic_flow_diagram(
                    str(info.get("name") or "Function"),
                    logic_flow,
                    logic_img_path,
                    all_calls=calls_list,
                    call_map=call_map if isinstance(call_map, dict) else None,
                )
            if not logic_img:
                logic_img = _render_call_graph_image(
                    str(info.get("name") or "Function"),
                    calls_list,
                    call_map if isinstance(call_map, dict) else None,
                    logic_img_path,
                    max_children=int(payload.get("logic_max_children") or LOGIC_MAX_CHILDREN_DEFAULT),
                    max_grandchildren=int(payload.get("logic_max_grandchildren") or LOGIC_MAX_GRANDCHILDREN_DEFAULT),
                    max_depth=int(payload.get("logic_max_depth") or LOGIC_MAX_DEPTH_DEFAULT),
                    module_map=module_map if isinstance(module_map, dict) else None,
                    condition_text=str(info.get("logic_condition") or ""),
                    true_path_text="\n".join([str(x) for x in (info.get("logic_true_calls") or []) if str(x).strip()]),
                    false_path_text="\n".join([str(x) for x in (info.get("logic_false_calls") or []) if str(x).strip()]),
                    return_path_text=str(info.get("logic_return_path") or ""),
                    error_path_text=str(info.get("logic_error_path") or ""),
                )
            # ⚠ 예전엔 여기서 Logic Diagram 행의 값 칸에 이미지 **파일명**을 넣었다.
            #   6·7열(실측상 유일하게 도달하는 폭)에선 라벨 사본 칸에 써서 화면에 나온
            #   적이 없는 죽은 쓰기였고, 새 배치에선 살아나 `logic` 본문을 덮는다.
            #   이미지는 아래 `_insert_logic_image_in_table` 이 그 칸에 직접 넣으므로
            #   파일명은 어차피 필요 없다 — 죽은 쓰기를 되살리는 대신 지운다.
            data_rows = [(FN_ROW_FULL, ["[ Function Information ]"])] + data_rows
            # ⚠ 표의 행 수는 **데이터가 정한다**(R54 N50). 예전엔 템플릿 표의 행 수(= 정본 그 함수의 파라미터 개수)를 하한으로
            #   두어(`max(len, 템플릿 행 수)`) 우리 행이 더 적은 함수마다 빈 라벨|값 행이 꼬리에 남았다 — 라이브 실측 516/989 표.
            #   그 전엔 그 값으로 **고정**이라 늘어난 파라미터가 조용히 잘렸다(무템플릿 경로는 하한 18). 둘 다 아니다.
            func_table = _add_blank_table(doc, len(data_rows), cols, style, None, None)
            _merge_function_info_table(func_table, cols, data_rows)
            _fill_function_info_table(func_table, data_rows)
            if logic_img:
                inserted = _insert_logic_image_in_table(func_table, cols, str(logic_img), picture_sink=_pics)
                if not inserted:
                    try:
                        from docx.shared import Inches  # type: ignore
                    except Exception:
                        Inches = None  # type: ignore
                    try:
                        doc.add_paragraph("Logic Diagram")
                        _pics.add_picture_paragraph(str(logic_img), width=Inches(5) if Inches else None)
                    except Exception as e:
                        _logger.warning("Failed to insert logic diagram: %s", e)
                        doc.add_paragraph("[Logic Diagram not available]")
            return func_table

        def _block_level(payload_la: Any, fallback: int) -> int:
            # heading payload 는 `(level, title)` 이지만 레벨이 문자열로 오는 템플릿이
            # 있다. 못 읽으면 호출부가 준 fallback 이 맞다(같은 파일의 기존 전방탐색도
            # 같은 처리를 한다). 판정은 바뀌지 않는다.
            try:
                return int(payload_la[0])
            except Exception:  # silent-ok — 레벨 파싱 실패는 fallback 이 정답이다
                return fallback

        for idx, block in enumerate(blocks):
            kind, payload_block = block
            # 버리는 중이면 **다음 형제/상위 heading 까지** 전부 버린다(본문·표 포함).
            # heading 만 지우고 아래를 남기면 그 내용이 엉뚱한 절에 붙는다.
            if _drop_until_level:
                if kind == "heading" and _block_level(payload_block,
                                                      _drop_until_level) <= _drop_until_level:
                    _drop_until_level = 0
                else:
                    continue
            if kind == "heading":
                level, title = payload_block
                # ── payload 에 없는 남의 함수 절 — 지울 것인가 ────────────────
                # 판정은 계측(`_note_fn_match`)과 **같은 함수**를 쓴다. 규칙이 갈리면
                # 세는 집합과 지우는 집합이 달라져 수치가 산출물을 설명하지 못한다.
                # `(삭제)` 표기 heading 은 `empty` 가 아니라 `deleted` 라 여기 안 걸린다 —
                # 템플릿이 의도해서 비운 자리이므로 그대로 둔다.
                if _drop_unmatched:
                    _key_peek = str(title).strip().lower()
                    if (_SWUFN_HEADING_RE.search(_key_peek)
                            and _fn_match_kind(
                                str(title),
                                _resolve_function_info(str(title), _key_peek)) == "empty"):
                        _dropped_headings.append(str(title)[:200])
                        _drop_until_level = _block_level(payload_block, 1)
                        continue
                if len(heading_stack) >= level:
                    heading_stack = heading_stack[: level - 1]
                heading_stack.append(str(title))
                doc.add_heading(title, level=level)
                key = str(title).strip().lower()
                next_kind = _next_block_kind(blocks, idx)
                has_table = _section_has_table(blocks, idx, level)
                if key == "overview":
                    _text_sections_placed.add("overview")
                    _add_docx_bullets(doc, overview)
                elif key in {
                    "introduction",
                    "purpose",
                    "scope",
                    "terms, abbreviations and definitions",
                    "reference",
                }:
                    # Preserve per-paragraph style (e.g. "List Paragraph")
                    # from the tokenized template so Scope bullets survive
                    # the rebuild path.
                    entries = template_section_block_map.get(key, [])
                    if entries:
                        _add_docx_section_paragraphs(doc, entries)
                    else:
                        template_text = template_section_map.get(key, "")
                        if template_text:
                            _add_docx_lines(doc, template_text)
                elif key == "requirements":
                    _text_sections_placed.add("requirements")
                    _add_docx_bullets(doc, requirements)
                elif key == "interfaces":
                    _text_sections_placed.add("interfaces")
                    _add_docx_bullets(doc, interfaces)
                elif key == "uds frames":
                    _text_sections_placed.add("uds_frames")
                    _add_docx_bullets(doc, uds_frames)
                elif key == "contents":
                    if not toc_inserted:
                        _add_docx_toc(doc)
                        toc_inserted = True
                elif key == "notes":
                    _text_sections_placed.add("notes")
                    _add_docx_bullets(doc, notes)
                elif key == "software unit design":
                    if next_kind != "table" and not has_table:
                        _add_docx_lines(doc, payload.get("software_unit_design", "") or "")
                elif key == "detailed uds":
                    _add_docx_text_block(doc, detailed_doc)
                elif key == "software unit structure":
                    # Keep this section text-only to avoid extra image
                    # between 2.5 and 2.5.1 (Software Unit Tables).
                    pass
                elif key == "unit structure":
                    swcom_id = ""
                    for item in reversed(heading_stack):
                        m = re.search(r"(SwCom_\d+)", item)
                        if m:
                            swcom_id = m.group(1)
                            break
                    interfaces_list: List[str] = []
                    internals_list: List[str] = []
                    if swcom_id and swcom_id in module_funcs:
                        interfaces_list = module_funcs[swcom_id].get("interfaces", [])
                        internals_list = module_funcs[swcom_id].get("internals", [])
                    if not interfaces_list:
                        interfaces_list = [
                            ln.strip()
                            for ln in (interface_functions or "").splitlines()
                            if ln.strip()
                        ][:8]
                    if not internals_list:
                        internals_list = [
                            ln.strip()
                            for ln in (internal_functions or "").splitlines()
                            if ln.strip()
                        ][:8]
                    structure_img = _render_unit_structure_image(
                        swcom_id or "Unit Structure",
                        interfaces_list,
                        internals_list,
                        Path(out).parent / "structure" / f"{swcom_id or 'unit'}.png",
                    )
                    if structure_img:
                        try:
                            from docx.shared import Inches  # type: ignore
                        except Exception:
                            Inches = None  # type: ignore
                        try:
                            doc.add_paragraph("Structure Diagram")
                            _pics.add_picture_paragraph(str(structure_img), width=Inches(5) if Inches else None)
                        except Exception as e:
                            _logger.warning("Failed to insert structure diagram: %s", e)
                            doc.add_paragraph("[Structure Diagram not available]")
                # 아래 3개는 **의도적 no-op**. 헤딩 아래 본문은 텍스트가 아니라
                # 구조화 데이터로 렌더되므로 여기서 또 쓰면 중복 출력된다:
                #   global data        → payload["global_vars"] 5열 테이블
                #   interface/internal → "unit structure" 다이어그램 + 함수 정보 테이블
                # (payload["global_data"] / ["unit_structure"] 텍스트를 여기 배선하지 말 것)
                elif key == "global data":
                    pass
                elif key == "interface functions":
                    pass
                elif key == "internal functions":
                    pass
                else:
                    section_text = _extract_doc_section(
                        detailed_doc or software_unit_design, title
                    )
                    if section_text:
                        _add_docx_text_block(doc, section_text, max_lines=200)
                    else:
                        doc.add_paragraph("N/A")

                if _SWUFN_HEADING_RE.search(key):
                    target_idx = None
                    for look_ahead in range(idx + 1, len(blocks)):
                        kind_la, payload_la = blocks[look_ahead]
                        if kind_la == "heading":
                            try:
                                level_la = int(payload_la[0])
                            except Exception:
                                level_la = level
                            if level_la <= level:
                                break
                            continue
                        if kind_la == "table":
                            (rows_la, cols_la, style_la, header_rows_la,
                             _ctx_titles_la, _el_la) = payload_la
                            if header_rows_la:
                                header_texts = [str(c or "").strip() for row in header_rows_la for c in row]
                                if any("Function Information" in c for c in header_texts):
                                    target_idx = look_ahead
                                    break
                    # (`swufn_table_spec` 조회는 제거 — 위 2829 주석 참조. 이 전방탐색이
                    #  같은 표를 찾아내며 실측 429/429 동일했다.)
                    # 템플릿 표에서는 열 수·스타일만 가져온다 — 행 수는 데이터가 정한다(R54 N50)
                    if target_idx is not None:
                        (_rows, cols, style, _header_rows,
                         _ctx_titles, _el_ti) = blocks[target_idx][1]
                    elif function_info_template:
                        _rows, cols, style, _header_rows = function_info_template
                    else:
                        cols, style = PARAM_GRID_COLS, None                  # 정본 그리드 폭(6)
                    info = _resolve_function_info(str(title), key)
                    _note_fn_match(str(title), info)
                    _build_function_info_table(info, cols, style)
                    if target_idx is not None:
                        skip_table_idx = target_idx
            elif kind == "table":
                if skip_table_idx == idx:
                    skip_table_idx = -1
                    continue
                rows, cols, style, header_rows, ctx_titles, tbl_el = payload_block
                ctx_text = " > ".join(ctx_titles).lower() if ctx_titles else ""
                current_swcom = _current_swcom_id()
                current_swcom_label = _current_swcom_label()
                data_rows: Optional[List[List[str]]] = None
                if header_rows:
                    header_texts = [str(c or "").strip() for row in header_rows for c in row]
                    if any("Function Information" in c for c in header_texts):
                        continue
                if "parameter definition" in ctx_text:
                    note = section_note_map.get("parameter definition", "")
                    if note and "parameter definition" not in note_added:
                        _add_docx_lines(doc, note)
                        note_added.add("parameter definition")
                elif "version information" in ctx_text:
                    note = section_note_map.get("version information", "")
                    if note and "version information" not in note_added:
                        _add_docx_lines(doc, note)
                        note_added.add("version information")
                if "software unit tables" in ctx_text:
                    data_rows = function_table_rows
                elif "common macro definition" in ctx_text:
                    data_rows = _table_rows_from_texts(common_macros, cols)
                elif "type definition" in ctx_text:
                    data_rows = _table_rows_from_texts(type_defs, cols)
                elif "parameter definition" in ctx_text:
                    data_rows = _table_rows_from_texts(param_defs, cols)
                elif "version information" in ctx_text:
                    data_rows = _table_rows_from_texts(version_defs, cols)
                elif "reference" in ctx_text:
                    refs = []
                    ref_files = payload.get("reference_files") or []
                    if isinstance(ref_files, list):
                        for name in ref_files:
                            if name:
                                refs.append([str(name), "", "", ""])
                    for ln in (notes or "").splitlines():
                        if ln.strip().startswith("doc:"):
                            refs.append([ln.strip()[4:], "", "", ""])
                    data_rows = refs if refs else None
                elif "global variables" in ctx_text:
                    header = header_rows[0] if header_rows else []
                    if globals_info_map and header:
                        names = [row[0] for row in global_vars if row]
                        names = _filter_global_names_by_swcom(
                            names,
                            current_swcom,
                            module_label=current_swcom_label,
                            static_only=False,
                        )
                        data_rows = _build_global_rows(
                            names,
                            globals_info_map,
                            header,
                            with_labels=False,
                        )
                    else:
                        data_rows = global_vars
                elif "static variables" in ctx_text:
                    header = header_rows[0] if header_rows else []
                    if globals_info_map and header:
                        names = [row[0] for row in static_vars if row]
                        names = _filter_global_names_by_swcom(
                            names,
                            current_swcom,
                            module_label=current_swcom_label,
                            static_only=True,
                        )
                        data_rows = _build_global_rows(
                            names,
                            globals_info_map,
                            header,
                            with_labels=False,
                        )
                    else:
                        data_rows = static_vars
                elif "calibration & parameter data" in ctx_text:
                    data_rows = _filter_rows_by_swcom(calibration_params, current_swcom, current_swcom_label)
                    if not data_rows and cols >= 4:
                        data_rows = [["N/A", "N/A", "N/A", "N/A"]]
                elif "macro" in ctx_text:
                    data_rows = []
                    for row in macro_defs:
                        if len(row) >= 4:
                            name, mtype, val, desc = row[0], row[1], row[2], row[3]
                        else:
                            name = row[0] if row else ""
                            mtype = ""
                            val = row[2] if len(row) > 2 else ""
                            desc = row[3] if len(row) > 3 else ""
                        if not mtype:
                            mtype = "Macro"
                        data_rows.append([name, mtype, val, desc])
                    data_rows = _filter_rows_by_swcom(data_rows, current_swcom, current_swcom_label)
                    if not data_rows and cols >= 4:
                        data_rows = [["N/A", "N/A", "N/A", "N/A"]]
                if data_rows is None and tbl_el is not None:
                    # 위 사슬이 하나도 안 걸렸다 = **생성기가 소유하지 않는 표**(이력·
                    # 참조 등)다. 모양만 복제하면 데이터 행이 빈칸으로 나가고, 빈칸은
                    # "이력 없음" 으로 읽힌다 — 실측으로 정본 이력 29행이 헤더만 남았다.
                    # ⚠ `data_rows == []` 는 다르다: 생성기가 소유하는데 **채울 게
                    #   없다**는 뜻이라 빈 표가 정답이다. `None` 과 접지 말 것.
                    # ⚠ 새로 만들지 않으므로 오히려 빠르다(정본은 표 1,165개).
                    try:
                        _append_body_block(doc, tbl_el, picture_sink=_pics)
                        _preserved_tables += 1
                    except Exception:   # noqa: BLE001 - 실패하면 종전대로 빈 표
                        _logger.warning("원본 표 복원 실패 — 빈 표로 대체", exc_info=True)
                        _add_blank_table(doc, rows, cols, style, header_rows, None)
                else:
                    # 표 크기는 **데이터**가 정한다. 템플릿 행수를 그대로 쓰면 두
                    # 방향으로 조용히 틀린다:
                    #  · 데이터가 많으면 잘린다 — 실측(표준 템플릿) 6개 표에서 1,144행
                    #    소실, `Software Unit Tables` 는 함수 57개 중 15개만 실렸다.
                    #  · 데이터가 적으면 빈 행이 남는다 — 실측(정본) 문서 전체 행의
                    #    28.2%가 완전 빈 행, `Software Unit Tables` 1,037행 중 978행.
                    # 같은 파일의 비-템플릿 경로 11곳은 이미 `max(len(rows) + 1, 2)` 로
                    # 데이터에 맞춰 잡는다 — 이 경로만 예외였다.
                    _n_hdr = min(len(header_rows or []), rows)
                    _want = _n_hdr + len(data_rows)
                    _rows_recovered += max(0, len(data_rows) - max(rows - _n_hdr, 0))
                    _rows_trimmed += max(0, rows - _want)
                    _add_blank_table(doc, max(_want, 1), cols, style, header_rows, data_rows)
            elif kind == "raw":
                # 선행 블록은 위에서 이미 붙였다(자동 목차보다 앞서야 해서).
                if idx >= _lead_raw:
                    try:
                        _append_body_block(doc, payload_block, picture_sink=_pics)
                        _restored_blocks += 1
                    except Exception:   # noqa: BLE001
                        _logger.warning("구조 블록 복원 실패", exc_info=True)
            elif kind == "para":
                text = str(payload_block.get("text") or "").strip()
                if not text:
                    continue
                if text.upper() == "N/A":
                    continue
                if heading_stack:
                    continue
                if re.match(r"^(Interfaces:|Internals:|Global data:)\s*\d+", text, flags=re.I):
                    continue
                style_name = str(payload_block.get("style") or "").strip()
                try:
                    if style_name:
                        doc.add_paragraph(text, style=style_name)
                    else:
                        doc.add_paragraph(text)
                except Exception:
                    doc.add_paragraph(text)
                if text.lower() == "contents" and not toc_inserted:
                    _add_docx_toc(doc)
                    toc_inserted = True
        _normalize_function_info_tables(doc)
        _remove_docx_paragraphs(doc, ["N/A"])
        _unmatched = sorted(_payload_fn_names - _matched_fn_names)
        # ⚠ **템플릿의 프로젝트 신원** (§6 후보 9). 참조 SUDS 와 **같은 판정 함수**를
        #    쓴다 — 새로 만들면 같은 질문에 답하는 판정이 둘이 되고, 이 저장소가 네 번
        #    겪은 "한쪽만 고쳐짐" 이 된다.
        #
        #    왜 필요한가: 템플릿은 heading 집합이 곧 문서의 함수 목록이다. 남의 프로젝트
        #    템플릿을 쓰면 ①이 프로젝트 함수가 heading 에 없어 **누락**되고 ②템플릿에만
        #    있는 남의 함수 heading 이 `_fallback_function_description` 으로 **합성 설명이
        #    붙은 섹션**으로 출력된다(:3088-3092). 실측(HDPDM01 템플릿 × KJPDS02 payload):
        #    payload 432개 중 95개(22.0%) 미반영 + 빈 heading 74개인데 판정은 `success`.
        #
        #    ⚠ 여기서 `ok`/`success` 판정을 뒤집지 않는다 — 템플릿이 의도된 부분집합인
        #      경우(회사 양식)가 실제로 있고, 그걸 실패로 만들면 정상 산출이 막힌다.
        #      **수치와 신원을 표면화**하고 판단은 사람에게 남긴다.
        _template_identity = _reference_identity_verdict(uds_payload, Path(str(template_path or "")))
        _stats = {
            "mode": "template",
            "template_path": str(template_path or ""),
            "template_source": template_source,
            "template_identity": _template_identity,
            "payload_functions": len(_payload_fn_names),
            "matched_functions": len(_matched_fn_names),
            # ⚠ 총량은 캡 **전**에 센다. 아래 sample 은 잘린 예시이므로 그 길이로 총량을
            #    되짚으면 안 된다(이 저장소가 반복해 겪은 함정).
            "unmatched_payload_count": len(_unmatched),
            "unmatched_payload_sample": _unmatched[:_STAT_SAMPLE_CAP],
            # 실제 갭 — 삭제 표기 heading 은 여기서 제외한다(아래 별도 축).
            "empty_heading_count": len(_empty_headings),
            "empty_heading_sample": _empty_headings[:_STAT_SAMPLE_CAP],
            # **지운** heading — 비워 둔 것과 다른 사실이다. `keep` 이면 0 이고, `drop` 이면
            # 그만큼이 위 `empty_heading_count` 에서 이리로 옮겨 온다(합은 보존된다).
            "dropped_heading_count": len(_dropped_headings),
            "dropped_heading_sample": _dropped_headings[:_STAT_SAMPLE_CAP],
            "unmatched_headings_mode": _unmatched_mode,
            # 의도된 빈 heading(템플릿이 "삭제" 로 표기) — 갭 아님. 섞으면 경고가 오탐이 된다.
            "deleted_heading_count": len(_deleted_headings),
            "deleted_heading_sample": _deleted_headings[:_STAT_SAMPLE_CAP],
            # 이름은 payload 에 있는데 내용이 전부 생성기 합성 — "반영" 으로 세면 부풀림.
            "boilerplate_only_count": len(_boilerplate_headings),
            "boilerplate_only_sample": _boilerplate_headings[:_STAT_SAMPLE_CAP],
            "match_pct": (
                round(100.0 * len(_matched_fn_names) / len(_payload_fn_names), 2)
                if _payload_fn_names else None      # 분모 0 = 미측정(0% 아님)
            ),
            # 템플릿에서 **그대로 가져온** 것. 보존은 옳지만(표지·이력이 그래야 한다)
            # 템플릿이 남의 프로젝트 문서면 그 값이 그대로 실리므로 침묵하면 안 된다.
            # 신원 판정(`template_identity`)과 짝으로 읽으라고 같이 낸다.
            "restored_template_blocks": _restored_blocks,
            "preserved_template_tables": _preserved_tables,
            "table_rows_recovered": _rows_recovered,
            "table_rows_blank_trimmed": _rows_trimmed,
            "swcom_globals_unattributed": len(_unattributed_swcoms),
            # (R50 N38) 본문이 있는데 템플릿(정본) 레이아웃에 자리가 없어 **실리지 않은 절** — 글자수. 정본 SwUDS 의
            #   1레벨 heading 엔 `Requirements` 가 없어 SwRS 요구 절이 매 run 침묵으로 빠졌다. 판정은 바꾸지 않는다
            #   (정본 레이아웃이 곧 회사 양식) — 사실만 낸다.
            "text_sections_unplaced": {
                k: len(str(v)) for k, v in (
                    ("overview", overview), ("requirements", requirements), ("interfaces", interfaces),
                    ("uds_frames", uds_frames), ("notes", notes),
                ) if str(v or "").strip() and k not in _text_sections_placed
            },
            # 참조 SUDS 를 얼마나·왜 적용했는지. 로그에만 남기면 산출물 검토자가 못 본다.
            "reference_suds": _ref_stats,
        }
        if _unattributed_swcoms:
            # 빈 표는 "이 컴포넌트엔 전역변수가 없다" 로 읽힌다 — 실제로는 **모른다** 다.
            # 침묵하면 그 오독을 못 막으므로 어느 컴포넌트인지까지 남긴다.
            _logger.warning(
                "전역/정적 변수를 귀속시키지 못한 컴포넌트 %d개 — 해당 표를 비웠다"
                "(전체를 싣던 종전 동작은 남의 컴포넌트에 이 프로젝트 전역변수를 전부 "
                "실었다). 대상: %s. payload 에 그 컴포넌트의 함수가 없으면 이렇게 된다 — "
                "템플릿이 payload 보다 넓은지 확인할 것.",
                len(_unattributed_swcoms), ", ".join(sorted(_unattributed_swcoms)[:12]),
            )
        if _ref_stats["safety_fields_blocked"]:
            _logger.warning(
                "참조 SUDS 의 ASIL·Related %d건을 적용하지 않았다 — 프로젝트 신원 미확인(%s). "
                "이 프로젝트의 SUDS 를 UDS_REF_SUDS_PATH 로 지정하면 적용된다.",
                _ref_stats["safety_fields_blocked"], _ref_stats["identity"]["reason"],
            )
        if _template_identity.get("same_project") is not True:
            _logger.warning(
                "템플릿의 프로젝트 신원을 확인하지 못했다(%s: template=%s vs payload=%s) — "
                "payload %d개 중 %d개 미반영, 빈 heading %d개. 템플릿 heading 집합이 곧 "
                "문서의 함수 목록이라, 남의 프로젝트 템플릿이면 이 프로젝트 함수가 누락되고 "
                "템플릿에만 있는 함수가 합성 설명과 함께 실린다. "
                "이 프로젝트의 템플릿을 지정할 것(생성 자체는 막지 않는다 — 의도된 부분집합일 수 있다).",
                _template_identity.get("reason"),
                _template_identity.get("ref_tokens"), _template_identity.get("payload_tokens"),
                len(_payload_fn_names), len(_unmatched), len(_empty_headings),
            )
        _struct_blocked_total = sum(_ref_stats["structural_fields_blocked"].values())
        if _struct_blocked_total:
            _logger.warning(
                "참조 SUDS 의 구조 축(입출력·전역·호출관계) %d건을 적용하지 않았다 — "
                "프로젝트 신원 미확인(%s). 축별: %s. "
                "이 칸은 SUTS 시험 대상 인터페이스 정의라 남의 프로젝트 값이 들어가면 "
                "존재하지 않는 인터페이스를 시험하는 문서가 된다.",
                _struct_blocked_total, _ref_stats["identity"]["reason"],
                _ref_stats["structural_fields_blocked"],
            )
        if _unmatched or _empty_headings or _boilerplate_headings:
            _logger.warning(
                "UDS DOCX 생성 충실도: payload 함수 %d개 중 %d개 반영(%.1f%%). "
                "템플릿에 대응 heading 이 없어 **문서에 반영되지 않은 함수 %d개**, "
                "내용이 전부 생성기 합성인 heading %d개, 내용 없이 남은 heading %d개 "
                "(삭제 표기 %d개는 갭에서 제외). 템플릿이 의도된 부분집합이 아니면 "
                "템플릿/프로젝트 설정을 확인할 것. 상세: %s",
                len(_payload_fn_names), len(_matched_fn_names),
                100.0 * len(_matched_fn_names) / max(len(_payload_fn_names), 1),
                len(_unmatched), len(_boilerplate_headings), len(_empty_headings),
                len(_deleted_headings), gen_stats_path(output_path).name,
            )
        if stats_out is not None:
            stats_out.update(_stats)
        _write_enriched_function_details(output_path, function_details, _ref_stats)
        _save_docx(doc, out, output_path, _stats)
        return str(out)

    # ── No-template fallback: SUDS-compatible 4-level structure ──
    doc = docx.Document()
    _pics = _PictureSink(doc)         # (R53 N27-c) 템플릿 분기와 같은 싱크(쌍둥이 한쪽만 고치지 않는다)
    cols = 6  # Function info table column count

    # ── Helper functions needed in fallback (template path has these in its scope) ──

    # Build callers_map from call_map (callee → [callers])
    _fb_callers_map: Dict[str, List[str]] = {}
    if isinstance(call_map, dict):
        for _fb_caller, _fb_callees in call_map.items():
            _fb_cname = _normalize_symbol_name(str(_fb_caller or "")).lower()
            if not _fb_cname or not isinstance(_fb_callees, list):
                continue
            for _fb_callee in _fb_callees:
                _fb_ce = _normalize_symbol_name(str(_fb_callee or "")).lower()
                if _fb_ce:
                    if _fb_ce not in _fb_callers_map:
                        _fb_callers_map[_fb_ce] = []
                    if _fb_cname not in _fb_callers_map[_fb_ce]:
                        _fb_callers_map[_fb_ce].append(_fb_cname)

    # Build swcom_global_hints and swcom_function_files for filtering
    _fb_swcom_global_hints: Dict[str, Set[str]] = {}
    _fb_swcom_function_files: Dict[str, Set[str]] = {}
    if isinstance(function_table_rows, list):
        for _fb_row in function_table_rows:
            if not isinstance(_fb_row, list) or len(_fb_row) < 4:
                continue
            _fb_sc = str(_fb_row[0] or "").strip()
            _fb_fn = str(_fb_row[3] or "").strip()
            if not _fb_sc or not _fb_fn:
                continue
            _fb_fi = function_details_by_name.get(_fb_fn.lower()) if isinstance(function_details_by_name, dict) else None
            if isinstance(_fb_fi, dict):
                _fb_fp = str(_fb_fi.get("file") or "").strip()
                if _fb_fp:
                    _fb_swcom_function_files.setdefault(_fb_sc, set()).add(Path(_fb_fp).name.lower())
                for _fb_gk in ["globals_global", "globals_static"]:
                    for _fb_g in (_fb_fi.get(_fb_gk) or []):
                        _fb_graw = str(_fb_g or "").strip()
                        if not _fb_graw:
                            continue
                        _fb_gtag = re.match(r"^\[(?:INOUT|IN|OUT)\]\s+(.+)$", _fb_graw)
                        _fb_gbase = _fb_gtag.group(1).strip() if _fb_gtag else _fb_graw
                        _fb_gn0 = re.split(r"(?:->|\.)", _fb_gbase)[0].strip()
                        if _fb_gn0:
                            _fb_swcom_global_hints.setdefault(_fb_sc, set()).add(_fb_gn0)

    def _fb_is_register_alias(name: str) -> bool:
        return bool(re.match(r"^REG_[A-Z0-9_]+$", str(name or "").strip()))

    def _fb_norm_stem(name: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
        for _sfx in ["itpds", "pds", "it", "main"]:
            if s.endswith(_sfx) and len(s) > len(_sfx) + 2:
                s = s[: -len(_sfx)]
        return s

    def _filter_global_names_by_swcom(
        all_names: List[str],
        swcom_id: str,
        module_label: str = "",
        static_only: Optional[bool] = None,
    ) -> List[str]:
        names = [str(n).strip() for n in all_names if str(n).strip() and not _fb_is_register_alias(str(n))]
        module_candidates: Set[str] = set()
        label_norm = re.sub(r"[^a-z0-9]+", "", str(module_label or "").lower())
        if label_norm:
            module_candidates.add(label_norm)
            module_candidates.add(label_norm.replace("system", "sys"))
            if "system" in label_norm and "os" in label_norm:
                module_candidates.add("sysos")
        selected: List[str] = []
        if module_candidates:
            for n in names:
                info_g = globals_info_map.get(n, {}) if isinstance(globals_info_map, dict) else {}
                is_static = str(info_g.get("static") or "").strip().lower() == "true"
                if static_only is True and not is_static:
                    continue
                if static_only is False and is_static:
                    continue
                gfile_l = str(info_g.get("file") or "").lower()
                gblob = re.sub(r"[^a-z0-9]+", "", gfile_l)
                if any(tok and tok in gblob for tok in module_candidates):
                    selected.append(n)
            if selected:
                return list(dict.fromkeys(selected))
        hints = _fb_swcom_global_hints.get(swcom_id, set())
        for n in names:
            info_g = globals_info_map.get(n, {}) if isinstance(globals_info_map, dict) else {}
            is_static = str(info_g.get("static") or "").strip().lower() == "true"
            if static_only is True and not is_static:
                continue
            if static_only is False and is_static:
                continue
            if n in hints:
                selected.append(n)
        if selected:
            return list(dict.fromkeys(selected))
        file_names = _fb_swcom_function_files.get(swcom_id, set())
        if not file_names:
            return names
        file_stems = {_fb_norm_stem(Path(x).stem) for x in file_names}
        for n in names:
            info_g = globals_info_map.get(n, {}) if isinstance(globals_info_map, dict) else {}
            is_static = str(info_g.get("static") or "").strip().lower() == "true"
            if static_only is True and not is_static:
                continue
            if static_only is False and is_static:
                continue
            gfile = str(info_g.get("file") or "").strip()
            gstem = _fb_norm_stem(Path(gfile).stem) if gfile else ""
            if gstem and any(gstem == fs or gstem.startswith(fs) or fs.startswith(gstem) for fs in file_stems):
                selected.append(n)
        return list(dict.fromkeys(selected))

    def _filter_rows_by_swcom(rows_in: List[List[str]], swcom_id: str, module_label: str = "") -> List[List[str]]:
        hints = _fb_swcom_global_hints.get(swcom_id, set())
        if not hints and module_label:
            lbl = re.sub(r"[^a-z0-9]+", "", module_label.lower())
            if "system" in lbl and "os" in lbl:
                hints = {"u8g_SystemTm_5ms", "u8g_SystemTm_10ms", "u8g_SystemTm_50ms", "u8s_InitiComplet_F"}
        if not hints:
            return []
        out_rows: List[List[str]] = []
        for row in (rows_in or []):
            if not isinstance(row, list) or not row:
                continue
            blob = " ".join([str(x or "") for x in row])
            if any(re.search(rf"\b{re.escape(h)}\b", blob) for h in hints):
                out_rows.append(row)
        return out_rows

    def _enhance_function_desc_with_ai(info: Dict[str, Any]) -> str:
        """Call AI to generate a better function description (1-3 sentences, Korean).

        Only called when ai_config is available and existing description is short (<30 chars).
        Returns enhanced description string, or empty string on failure.
        """
        if not ai_config:
            return ""
        try:
            from workflow.ai import agent_call  # type: ignore
        except ImportError:
            return ""

        _UDS_AI_SYSTEM_PROMPT = (
            "당신은 자동차 ECU 소프트웨어 단위 설계 명세서(SUDS) 작성 전문가입니다. "
            "ISO 26262 ASIL 기준에 따라 C 함수의 기술적 설명을 1~3문장으로 작성합니다.\n"
            "규칙:\n"
            "- 함수의 목적, 입출력, 주요 동작을 포함하세요.\n"
            "- 한국어로 작성하세요.\n"
            "- JSON 형식으로 반환: {\"description\": \"...\", \"purpose\": \"...\"}"
        )
        fn_name = info.get("name", "")
        prototype = info.get("prototype", "")
        inputs = ", ".join(str(i) for i in (info.get("inputs") or [])[:5])
        outputs = str(info.get("output") or "")
        calls = ", ".join(str(c) for c in (info.get("calls_list") or [])[:5])
        user_msg = (
            f"함수명: {fn_name}\n"
            f"원형: {prototype}\n"
            f"입력: {inputs or 'N/A'}\n"
            f"출력: {outputs or 'N/A'}\n"
            f"호출 함수: {calls or 'N/A'}\n"
            "위 정보를 바탕으로 기술적 함수 설명을 JSON으로 반환하세요."
        )
        import json as _json
        import threading
        result_holder: Dict[str, str] = {}
        def _call():
            try:
                r = agent_call(
                    ai_config,
                    [{"role": "system", "content": _UDS_AI_SYSTEM_PROMPT},
                     {"role": "user", "content": user_msg}],
                    stage="uds_enhance",
                )
                raw = (r.get("output") or "").strip()
                # Try JSON extraction
                m = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
                if m:
                    parsed = _json.loads(m.group())
                    result_holder["desc"] = str(parsed.get("description") or parsed.get("purpose") or "")
                else:
                    result_holder["desc"] = raw[:200]
            except Exception:
                pass
        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=20)
        return result_holder.get("desc", "")

    def _build_function_info_table(info: Dict[str, Any], _cols: int, style: Any) -> None:
        """Build and append a function info table to doc."""
        _fn_key = str(info.get("name") or "").strip().lower()
        # Resolve called/calling
        _callee_names = list(dict.fromkeys(
            _normalize_symbol_name(str(c)).lower()
            for c in (info.get("calls_list") or []) if str(c).strip()
        ))
        if not _callee_names and isinstance(call_map, dict):
            _fn_norm = _normalize_symbol_name(_fn_key).lower()
            for _ck, _vals in call_map.items():
                if _normalize_symbol_name(str(_ck or "")).lower() == _fn_norm and isinstance(_vals, list):
                    _callee_names = list(dict.fromkeys(str(x).strip() for x in _vals if str(x).strip()))
                    break
        _caller_names = list(dict.fromkeys(_fb_callers_map.get(_fn_key, [])))

        def _sig_lines(names: List[str]) -> List[str]:
            out: List[str] = []
            for nm in names:
                sig = ""
                _ci = function_details_by_name.get(str(nm).lower()) if isinstance(function_details_by_name, dict) else None
                if isinstance(_ci, dict):
                    sig = str(_ci.get("prototype") or "").strip()
                out.append(sig or str(nm))
            return [x for x in out if x]

        _inf2 = dict(info)
        _inf2["called"] = "\n".join(_sig_lines(_callee_names)) if _callee_names else "N/A"
        if not str(_inf2.get("calling") or "").strip():
            _inf2["calling"] = "\n".join(_sig_lines(_caller_names)) if _caller_names else "N/A"
        if _fn_key == "main" and not str(_inf2.get("calling") or "").strip().replace("N/A", ""):
            _inf2["calling"] = "void _Startup(void)"

        # AI-enhance description if it's short
        _existing_desc = str(_inf2.get("description") or _inf2.get("desc") or "").strip()
        if ai_config and len(_existing_desc) < 30:
            _ai_desc = _enhance_function_desc_with_ai(_inf2)
            if _ai_desc and len(_ai_desc) > len(_existing_desc):
                _inf2["description"] = _ai_desc

        _g_in, _g_out = resolve_param_grid_entries(
            _inf2, globals_info_map, struct_member_types)
        _inf2["_param_grid_inputs"] = _g_in
        _inf2["_param_grid_outputs"] = _g_out
        _data_rows = _build_function_info_layout(_inf2, _cols)
        # Attempt logic diagram
        _logic_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(_inf2.get("id") or _fn_key or "fn")).strip("_")
        _logic_img_path = Path(out).parent / "logic" / f"{_logic_key}.png"
        _calls_list2 = _callee_names or _extract_call_names(str(_inf2.get("called") or ""))
        # 캐싱: 이미지가 이미 존재하면 재생성 건너뛰기
        _logic_img = str(_logic_img_path) if _logic_img_path.exists() and _logic_img_path.stat().st_size > 100 else None
        if not _logic_img:
            _logic_img = _render_call_graph_image(
                str(_inf2.get("name") or "Function"),
                _calls_list2,
                call_map if isinstance(call_map, dict) else None,
                _logic_img_path,
                max_children=int(payload.get("logic_max_children") or LOGIC_MAX_CHILDREN_DEFAULT),
                max_grandchildren=int(payload.get("logic_max_grandchildren") or LOGIC_MAX_GRANDCHILDREN_DEFAULT),
                max_depth=int(payload.get("logic_max_depth") or LOGIC_MAX_DEPTH_DEFAULT),
                module_map=module_map if isinstance(module_map, dict) else None,
            )
        _data_rows = [(FN_ROW_FULL, ["[ Function Information ]"])] + _data_rows
        _ft = _add_blank_table(doc, len(_data_rows), _cols, style, None, None)   # (R54 N50) 행 수는 데이터가 정한다 — 하한 18 은 빈 꼬리 행이었다
        _merge_function_info_table(_ft, _cols, _data_rows)
        _fill_function_info_table(_ft, _data_rows)
        if _logic_img:
            if not _insert_logic_image_in_table(_ft, _cols, str(_logic_img), picture_sink=_pics):
                try:
                    from docx.shared import Inches as _I  # type: ignore
                    doc.add_paragraph("Logic Diagram")
                    _pics.add_picture_paragraph(str(_logic_img), width=_I(5))
                except Exception:
                    doc.add_paragraph("[Logic Diagram not available]")

    # ── Cover ──
    doc.add_heading("Software Unit Design Specification", level=1)
    doc.add_paragraph(f"Project: {project}")
    doc.add_paragraph(f"Generated at: {generated_at}")
    if payload.get("job_url"):
        doc.add_paragraph(f"Job URL: {payload.get('job_url')}")
    if payload.get("build_number"):
        doc.add_paragraph(f"Build: {payload.get('build_number')}")

    # ── Revision History ──
    doc.add_heading("Revision History", level=2)
    _add_blank_table(
        doc, 3, 6, None,
        [["Version", "Date", "Description", "Author", "Reviewer", "Approver"]],
        [["", "", "", "", "", ""], ["", "", "", "", "", ""]],
    )

    # ── Introduction ──
    doc.add_heading("Introduction", level=2)
    for _subsec in ["Purpose", "Scope", "Terms, Abbreviations and Definitions", "Reference"]:
        doc.add_heading(_subsec, level=3)
        doc.add_paragraph("N/A")

    # ── Contents ──
    doc.add_heading("Contents", level=2)
    _add_docx_toc(doc)

    # ── Common Macro Definition ──
    if common_macros:
        doc.add_heading("Common Macro Definition", level=2)
        _cm_rows = _table_rows_from_texts(common_macros, 4)
        _add_blank_table(doc, max(len(_cm_rows) + 1, 2), 4, None,
                         [["Macro name", "Type", "Define", "Description"]], _cm_rows)

    # ── Type Definition ──
    if type_defs:
        doc.add_heading("Type Definition", level=2)
        _td_rows = _table_rows_from_texts(type_defs, 4)
        _add_blank_table(doc, max(len(_td_rows) + 1, 2), 4, None,
                         [["Type", "Define", "Range", "Description"]], _td_rows)

    # ── Parameter Definition ──
    if param_defs:
        doc.add_heading("Parameter Definition", level=2)
        _pd_rows = _table_rows_from_texts(param_defs, 4)
        _add_blank_table(doc, max(len(_pd_rows) + 1, 2), 4, None,
                         [["Parameter", "Type", "Define", "Description"]], _pd_rows)

    # ── Version Information ──
    if version_defs:
        doc.add_heading("Version Information", level=2)
        _vd_rows = _table_rows_from_texts(version_defs, 4)
        _add_blank_table(doc, max(len(_vd_rows) + 1, 2), 4, None,
                         [["File Name", "Version", "Date", "Note"]], _vd_rows)

    # ── Software Unit Structure ──
    doc.add_heading("Software Unit Structure", level=2)
    doc.add_heading("Software Unit Tables", level=3)
    if function_table_rows:
        _su_data = [
            [str(r[0] or ""), str(r[3] or ""), ""]
            for r in function_table_rows
            if isinstance(r, list) and len(r) >= 4
        ]
        _add_blank_table(doc, len(_su_data) + 1, 3, None,
                         [["Component", "Function", "Comment"]], _su_data)

    # ── Build SwCom grouping from function_table_rows ──
    _swcom_order: List[str] = []
    _swcom_func_map: Dict[str, Dict[str, List]] = {}
    for _row in (function_table_rows or []):
        if not isinstance(_row, list) or len(_row) < 4:
            continue
        _sc = str(_row[0] or "").strip()
        _fid = str(_row[2] or "").strip()
        _fn = str(_row[3] or "").strip()
        _ft = str(_row[4] or "").strip().lower() if len(_row) > 4 else ""
        if not _sc or not _fn:
            continue
        if _sc not in _swcom_func_map:
            _swcom_order.append(_sc)
            _swcom_func_map[_sc] = {"interfaces": [], "internals": []}
        _is_iface = "i/f" in _ft or _ft == "if"
        (_swcom_func_map[_sc]["interfaces"] if _is_iface else _swcom_func_map[_sc]["internals"]).append((_fid, _fn))

    # Fallback: no function_table_rows — put everything under SwCom_Unknown
    if not _swcom_order and isinstance(function_details, dict) and function_details:
        _swcom_order = ["SwCom_Unknown"]
        _swcom_func_map["SwCom_Unknown"] = {"interfaces": [], "internals": []}
        for _fid_k, _inf_v in function_details.items():
            if not isinstance(_inf_v, dict):
                continue
            _swcom_func_map["SwCom_Unknown"]["internals"].append(
                (str(_fid_k).strip(), str(_inf_v.get("name") or "").strip())
            )

    _GLOBAL_HDR = ["Name", "Type", "Value Range", "Reset Value", "Description"]
    _MACRO_HDR  = ["Name", "Type", "Value", "Description"]
    _CALIB_HDR  = ["Signal", "Type", "Value", "Description"]

    def _na_row(n: int) -> List[str]:
        return ["N/A"] + [""] * (n - 1)

    # ── Software Unit Design (H2: SwCom, H3: sections, H4: functions) ──
    doc.add_heading("Software Unit Design", level=2)

    fn_added = 0
    for _swcom_id in _swcom_order:
        _sc_label = ""
        # Try to get component label from sds_partition_map
        if isinstance(sds_partition_map, dict):
            for _k, _v in sds_partition_map.items():
                if _swcom_id.lower() in _k.lower() or _k.lower() in _swcom_id.lower():
                    _sc_label = str(_v.get("name") or _v.get("description") or "").strip()
                    break
        _sc_heading = f"{_swcom_id} ({_sc_label})" if _sc_label else _swcom_id
        doc.add_heading(_sc_heading, level=2)

        # ── Unit Structure ──
        doc.add_heading("Unit Structure", level=3)
        _iface_names = [_fn for _, _fn in _swcom_func_map[_swcom_id]["interfaces"]]
        _intern_names = [_fn for _, _fn in _swcom_func_map[_swcom_id]["internals"]]
        _struct_img = _render_unit_structure_image(
            _swcom_id, _iface_names, _intern_names,
            Path(out).parent / "structure" / f"{_swcom_id}.png",
        )
        if _struct_img:
            try:
                from docx.shared import Inches as _Inches  # type: ignore
                _pics.add_picture_paragraph(str(_struct_img), width=_Inches(5))
            except Exception:
                doc.add_paragraph(f"[Unit Structure: {_swcom_id}]")
        else:
            doc.add_paragraph(
                f"Interface Functions: {len(_iface_names)}, "
                f"Internal Functions: {len(_intern_names)}"
            )

        # ── Global Data ──
        doc.add_heading("Global Data", level=3)

        # Global variables
        doc.add_heading("Global variables", level=4)
        _gnames_all = [_r[0] for _r in (global_vars or []) if _r]
        _gnames = _filter_global_names_by_swcom(_gnames_all, _swcom_id, _sc_label, static_only=False)
        if _gnames and globals_info_map:
            _g_rows = _build_global_rows(_gnames, globals_info_map, _GLOBAL_HDR, with_labels=False)
        else:
            _g_rows = [list(_r) for _r in (global_vars or []) if _r]
        _add_blank_table(doc, max(len(_g_rows) + 1, 2), 5, None,
                         [_GLOBAL_HDR], _g_rows or [_na_row(5)])

        # Static Variables
        doc.add_heading("Static Variables", level=4)
        _snames_all = [_r[0] for _r in (static_vars or []) if _r]
        _snames = _filter_global_names_by_swcom(_snames_all, _swcom_id, _sc_label, static_only=True)
        if _snames and globals_info_map:
            _s_rows = _build_global_rows(_snames, globals_info_map, _GLOBAL_HDR, with_labels=False)
        else:
            _s_rows = [list(_r) for _r in (static_vars or []) if _r]
        _add_blank_table(doc, max(len(_s_rows) + 1, 2), 5, None,
                         [_GLOBAL_HDR], _s_rows or [_na_row(5)])

        # Macro
        doc.add_heading("Macro", level=4)
        _m_rows = _filter_rows_by_swcom(list(macro_defs or []), _swcom_id, _sc_label)
        _add_blank_table(doc, max(len(_m_rows) + 1, 2), 4, None,
                         [_MACRO_HDR], _m_rows or [_na_row(4)])

        # Calibration & Parameter Data
        doc.add_heading("Calibration & Parameter Data", level=4)
        _c_rows = _filter_rows_by_swcom(list(calibration_params or []), _swcom_id, _sc_label)
        _add_blank_table(doc, max(len(_c_rows) + 1, 2), 4, None,
                         [_CALIB_HDR], _c_rows or [_na_row(4)])

        def _write_fn_section(fn_pairs: List, heading: str, h_level: int) -> None:
            nonlocal fn_added
            if not fn_pairs:
                return
            doc.add_heading(heading, level=h_level)
            for _fid2, _fname2 in fn_pairs:
                _h = f"{_fid2}: {_fname2}" if _fid2 else _fname2
                doc.add_heading(_h, level=h_level + 1)
                _inf = (
                    (function_details.get(_fid2) if isinstance(function_details, dict) else None)
                    or (function_details_by_name.get(_fname2.lower()) if isinstance(function_details_by_name, dict) else None)
                    or {"id": _fid2, "name": _fname2}
                )
                if not isinstance(_inf, dict):
                    _inf = {"id": _fid2, "name": _fname2}
                _build_function_info_table(_inf, cols, None)
                fn_added += 1

        _write_fn_section(_swcom_func_map[_swcom_id]["interfaces"], "Interface Functions", 3)
        _write_fn_section(_swcom_func_map[_swcom_id]["internals"], "Internal Functions", 3)

    # ── Logic Diagrams (optional) ──
    logic_items = payload.get("logic_diagrams") if isinstance(payload, dict) else []
    logic_items = _merge_logic_ai_items(logic_items, ai_sections)
    if isinstance(logic_items, list) and logic_items:
        try:
            from docx.shared import Inches  # type: ignore
        except Exception:
            Inches = None  # type: ignore
        doc.add_heading("Logic Diagrams", level=2)
        for item in logic_items:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or "Logic Diagram"
            path = item.get("path")
            desc = item.get("description") or ""
            if title:
                doc.add_paragraph(str(title))
            if path:
                try:
                    _pics.add_picture_paragraph(str(path), width=Inches(5) if Inches else None)
                except Exception:
                    continue
            if desc:
                doc.add_paragraph(str(desc))

    # 비템플릿 폴백 — 문서를 payload 로부터 새로 쓰므로 반영 누락이 원리적으로 없다.
    # 그래도 mode 를 남긴다(통계 부재를 "정상"으로 오독하지 않게).
    _nt_fn_names = {
        _normalize_symbol_name(str(v.get("name"))).lower()
        for src in (payload.get("function_details"), payload.get("function_details_by_name"))
        if isinstance(src, dict)
        for v in src.values()
        if isinstance(v, dict) and v.get("name")
    }
    _nt_stats = {
        "mode": "no_template",
        "template_path": "",
        "template_source": "none",
        "payload_functions": len(_nt_fn_names),
        "matched_functions": len(_nt_fn_names),
        "unmatched_payload_count": 0,
        "unmatched_payload_sample": [],
        "empty_heading_count": 0,
        "empty_heading_sample": [],
        "match_pct": 100.0 if _nt_fn_names else None,
        # ⚠ 이 키가 **없었다**. 참조 SUDS 병합 루프는 템플릿/폴백 분기보다 **위**에서
        #    항상 돌기 때문에, 폴백 모드에서도 남의 프로젝트 문서 값이 들어간다. 그런데
        #    사이드카에는 흔적이 하나도 안 남아 검토자가 "참조를 안 썼다" 로 읽었다.
        #    템플릿 경로에만 기록을 넣은 전형적인 "한쪽만 고침" 이라 여기서 닫는다.
        "reference_suds": _ref_stats,
    }
    if stats_out is not None:
        stats_out.update(_nt_stats)
    _write_enriched_function_details(output_path, function_details, _ref_stats)
    _save_docx(doc, out, output_path, _nt_stats)
    return str(out)


