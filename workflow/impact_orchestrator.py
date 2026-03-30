from __future__ import annotations

import os
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from backend.schemas import ScmLinkedDocs, ScmUpdateRequest
from backend.services.scm_registry import get_registry_entry, update_entry
from workflow.change_trigger import ChangeTrigger
from workflow.delta_update import classify_changed_functions
from workflow.impact_audit import acquire_run_lock, release_run_lock, write_impact_audit
from workflow.impact_changes import build_change_log, write_change_log


REPO_ROOT = Path(__file__).resolve().parents[1]
AUTO_DOCS = {"uds", "suts", "sits"}
FLAG_DOCS = {"sts", "sds"}
# Default matrix — AUTO targets are only executed when trigger.auto_generate=True;
# otherwise they are downgraded to FLAG at runtime.
ACTION_MATRIX: Dict[str, Dict[str, str]] = {
    # sits: cross-module integration — AUTO on any functional change, FLAG on header-only
    "SIGNATURE": {"uds": "AUTO", "suts": "AUTO", "sits": "AUTO", "sts": "FLAG", "sds": "FLAG"},
    "BODY":      {"uds": "AUTO", "suts": "AUTO", "sits": "AUTO", "sts": "FLAG", "sds": "-"},
    "NEW":       {"uds": "AUTO", "suts": "AUTO", "sits": "AUTO", "sts": "FLAG", "sds": "FLAG"},
    "DELETE":    {"uds": "AUTO", "suts": "AUTO", "sits": "AUTO", "sts": "FLAG", "sds": "FLAG"},
    "VARIABLE":  {"uds": "AUTO", "suts": "AUTO", "sits": "AUTO", "sts": "FLAG", "sds": "-"},
    "HEADER":    {"uds": "AUTO", "suts": "FLAG", "sits": "FLAG", "sts": "FLAG", "sds": "FLAG"},
}


def _load_source_sections(source_root: str) -> Dict[str, Any]:
    try:
        from backend.helpers import _get_source_sections_cached

        return _get_source_sections_cached(source_root)
    except Exception:
        import report_generator as rg

        return rg.generate_uds_source_sections(source_root)


@dataclass
class ImpactOptions:
    max_hop: int = 2
    same_module_only: bool = True
    max_impacted_functions: int = 50


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _resolve_existing(path_text: str) -> str | None:
    path = Path(str(path_text or "").strip()).expanduser()
    return str(path.resolve()) if path.exists() and path.is_file() else None


def _discover_doc(name_token: str, suffixes: Set[str]) -> str | None:
    docs_dir = REPO_ROOT / "docs"
    if not docs_dir.exists():
        return None
    for path in docs_dir.iterdir():
        if path.is_file() and path.suffix.lower() in suffixes and name_token.lower() in path.name.lower():
            return str(path.resolve())
    return None


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _extract_req_ids(info: Dict[str, Any]) -> List[str]:
    text = " ".join(
        [
            str(info.get("related") or ""),
            str(info.get("comment_related") or ""),
            str(info.get("srs_req_ids") or ""),
            ", ".join(str(x) for x in (info.get("hsis_related_ids") or [])),
        ]
    )
    reqs = re.findall(r"\bSw(?:TR|TSR|NTR|NTSR|CNF|EI|ST|STR|Fn|TK|Com)_\d+\b", text)
    return list(dict.fromkeys(reqs))


def _load_linked_doc_summary(linked_doc: str) -> Dict[str, Any]:
    if not linked_doc:
        return {}
    payload_path = Path(linked_doc).with_suffix(".payload.json")
    if not payload_path.exists():
        return {}
    payload = _load_json(payload_path)
    quality = payload.get("quality_report") if isinstance(payload.get("quality_report"), dict) else {}
    trace = payload.get("trace_coverage") if isinstance(payload.get("trace_coverage"), dict) else {}
    req_cov = quality.get("requirement_coverage") if isinstance(quality.get("requirement_coverage"), dict) else {}
    return {
        "payload_path": str(payload_path),
        "test_case_count": payload.get("test_case_count") or quality.get("total_test_cases") or "",
        "requirement_coverage_pct": req_cov.get("pct", ""),
        "trace_coverage_pct": trace.get("pct", ""),
    }


def _update_linked_doc(entry_id: str, field: str, path_text: str) -> None:
    entry = get_registry_entry(entry_id)
    if entry is None:
        return
    merged = entry.linked_docs.model_dump(mode="json")
    merged[field] = path_text
    update_entry(entry_id, ScmUpdateRequest(linked_docs=ScmLinkedDocs(**merged)))


def _load_uds_fn_details(
    linked_doc: str, flagged_fns: List[str]
) -> Dict[str, Dict[str, Any]]:
    """Load UDS spec fields per flagged function from the payload sidecar."""
    if not linked_doc:
        return {}
    payload_path = Path(linked_doc).with_suffix(".payload.json")
    if not payload_path.exists():
        return {}
    payload = _load_json(payload_path)
    by_name: Dict[str, Any] = payload.get("function_details_by_name") or {}
    if not by_name:
        for info in (payload.get("function_details") or {}).values():
            if isinstance(info, dict) and info.get("name"):
                by_name[str(info["name"]).strip().lower()] = info
    result: Dict[str, Dict[str, Any]] = {}
    for fn in flagged_fns:
        key = fn.strip().lower()
        info = by_name.get(key) or {}
        if info:
            result[fn] = {
                "description": str(info.get("description") or ""),
                "inputs": info.get("inputs") or [],
                "outputs": info.get("outputs") or [],
                "asil": str(info.get("asil") or ""),
                "related": str(info.get("related") or ""),
            }
    return result


def _load_suts_fn_tcs(
    linked_doc: str, flagged_fns: List[str]
) -> Dict[str, List[str]]:
    """Return {fn_name: [tc_id, ...]} by parsing the existing SUTS xlsm.
    Falls back to empty dict on any error (file missing, parse failure, etc.)."""
    if not linked_doc or not Path(linked_doc).exists():
        return {}
    try:
        from tools.export_suts_vectorcast import build_vectorcast_model  # type: ignore
        model = build_vectorcast_model(linked_doc, target_functions=flagged_fns)
        result: Dict[str, List[str]] = {}
        for unit in model.get("units") or []:
            name = str(unit.get("unit_name") or "").strip()
            # each test_case row carries base_tc_id (the TC block identifier)
            tcs = [str(tc.get("base_tc_id") or "") for tc in unit.get("test_cases") or [] if tc.get("base_tc_id")]
            if name and tcs:
                result[name] = list(dict.fromkeys(tcs))
        return result
    except Exception:
        return {}


def _load_sits_fn_chains(
    linked_doc: str, flagged_fns: List[str]
) -> Dict[str, List[str]]:
    """Return {entry_fn: [label, ...]} from the SITS vectorcast intermediate JSON."""
    if not linked_doc:
        return {}
    stem = Path(linked_doc).stem
    intermediate = Path(linked_doc).with_name(stem + "_vectorcast.json")
    if not intermediate.exists():
        return {}
    data = _load_json(intermediate)
    fn_set = {fn.strip().lower() for fn in flagged_fns}
    result: Dict[str, List[str]] = {}
    for itc in data.get("integrations") or []:
        entry = str(itc.get("entry_fn") or "").strip()
        if entry.lower() in fn_set:
            chain = str(itc.get("call_chain") or "").strip()
            tc_id = str(itc.get("tc_id") or "")
            label = f"{tc_id}: {chain}" if tc_id else chain
            if label:
                result.setdefault(entry, []).append(label)
    return result


def _write_review_artifact(
    target: str,
    trigger: ChangeTrigger,
    changed_types: Dict[str, str],
    impact_groups: Dict[str, List[str]],
    by_name: Dict[str, Dict[str, Any]] | None = None,
    linked_doc: str = "",
) -> str:
    review_dir = REPO_ROOT / "reports" / "impact_audit"
    review_dir.mkdir(parents=True, exist_ok=True)
    out_path = review_dir / f"{target}_review_required_{_ts()}.md"
    by_name = by_name or {}
    doc_summary = _load_linked_doc_summary(linked_doc)
    modules: List[str] = []
    files: List[str] = []
    related_ids: List[str] = []
    for func in impact_groups.get("direct", []) or []:
        info = by_name.get(str(func).lower()) or {}
        mod = str(info.get("module_name") or "").strip()
        fp = str(info.get("file") or "").strip()
        if mod:
            modules.append(mod)
        if fp:
            files.append(fp)
        related_ids.extend(_extract_req_ids(info))
    modules = list(dict.fromkeys(modules))
    files = list(dict.fromkeys(files))
    related_ids = list(dict.fromkeys(related_ids))
    lines = [
        f"# {target.upper()} Review Required",
        "",
        f"- SCM ID: `{trigger.scm_id}`",
        f"- Trigger: `{trigger.trigger_type}`",
        f"- Source root: `{trigger.source_root}`",
        f"- Base ref: `{trigger.base_ref}`",
        f"- Linked document: `{linked_doc or '-'}`",
    ]
    if doc_summary:
        lines.extend(
            [
                f"- Linked payload: `{doc_summary.get('payload_path') or '-'}`",
                f"- Linked test cases: `{doc_summary.get('test_case_count') or '-'}`",
                f"- Linked requirement coverage: `{doc_summary.get('requirement_coverage_pct') or '-'}`",
                f"- Linked trace coverage: `{doc_summary.get('trace_coverage_pct') or '-'}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Changed Files",
        ]
    )
    lines.extend([f"- `{item}`" for item in trigger.changed_files] or ["- none"])
    lines.extend(["", "## Changed Functions"])
    if changed_types:
        for func, kind in sorted(changed_types.items()):
            lines.append(f"- `{func}` : `{kind}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Context"])
    lines.append(f"- Modules: `{', '.join(modules) if modules else '-'}`")
    lines.append(f"- Source files: `{', '.join(files[:6]) if files else '-'}`")
    lines.append(f"- Related requirements: `{', '.join(related_ids[:12]) if related_ids else '-'}`")
    lines.extend(["", "## Impact"])
    lines.append(f"- direct: `{len(impact_groups.get('direct', []))}`")
    lines.append(f"- indirect_1hop: `{len(impact_groups.get('indirect_1hop', []))}`")
    lines.append(f"- indirect_2hop: `{len(impact_groups.get('indirect_2hop', []))}`")
    # --- Function Details section ---
    change_kinds = set(changed_types.values())
    is_signature = "SIGNATURE" in change_kinds
    is_header = "HEADER" in change_kinds
    flagged_fns = list(changed_types.keys())
    # Load document-specific data (best-effort; empty dict if linked_doc missing)
    uds_doc_details: Dict[str, Any] = _load_uds_fn_details(linked_doc, flagged_fns) if target == "uds" else {}
    suts_tcs: Dict[str, Any] = _load_suts_fn_tcs(linked_doc, flagged_fns) if target == "suts" else {}
    sits_chains: Dict[str, Any] = _load_sits_fn_chains(linked_doc, flagged_fns) if target == "sits" else {}

    lines.extend(["", "## Function Details"])
    for fn, kind in sorted(changed_types.items()):
        src = by_name.get(fn.lower()) or {}
        lines.append(f"\n### `{fn}` ({kind})")

        # ── Source-level info (always available from by_name) ──────────────
        src_module    = str(src.get("module_name") or "").strip()
        src_file      = str(src.get("file") or "").strip()
        src_prototype = str(src.get("prototype") or "").strip()
        src_desc      = str(src.get("description") or src.get("comment") or "").strip()
        src_inputs    = src.get("inputs") or src.get("params") or []
        src_outputs   = src.get("outputs") or []
        src_calls     = src.get("calls_list") or src.get("calls") or []
        src_asil      = str(src.get("asil") or "").strip()
        src_req_ids   = _extract_req_ids(src)

        lines.append("**소스 현황:**")
        if src_module:
            lines.append(f"- 모듈: `{src_module}`")
        if src_file:
            lines.append(f"- 파일: `{src_file}`")
        if src_prototype:
            lines.append(f"- 프로토타입: `{src_prototype}`")
        if src_desc:
            lines.append(f"- 설명 (주석): {src_desc[:300]}{'...' if len(src_desc) > 300 else ''}")
        if src_inputs:
            lines.append(f"- 입력 파라미터: `{', '.join(str(x) for x in src_inputs[:8])}`")
        if src_outputs:
            lines.append(f"- 출력: `{', '.join(str(x) for x in src_outputs[:6])}`")
        if src_asil:
            lines.append(f"- ASIL: `{src_asil}`")
        if src_calls:
            lines.append(f"- 호출하는 함수: `{', '.join(str(x) for x in src_calls[:8])}`")
        if src_req_ids:
            lines.append(f"- 연관 요구사항: `{', '.join(src_req_ids[:10])}`")
        if not any([src_module, src_file, src_prototype, src_inputs, src_outputs, src_calls]):
            lines.append("- (소스 파싱 정보 없음)")

        # ── Document-specific info (from linked payload) ───────────────────
        if target == "uds":
            det = uds_doc_details.get(fn) or {}
            if det:
                lines.append("")
                lines.append("**UDS 스펙 현황 (링크 문서):**")
                doc_desc = (det.get("description") or "").strip()
                if doc_desc:
                    lines.append(f"- 현재 설명: {doc_desc[:300]}{'...' if len(doc_desc) > 300 else ''}")
                doc_in = det.get("inputs") or []
                if doc_in:
                    lines.append(f"- 현재 inputs: `{', '.join(str(x) for x in doc_in[:6])}`")
                doc_out = det.get("outputs") or []
                if doc_out:
                    lines.append(f"- 현재 outputs: `{', '.join(str(x) for x in doc_out[:6])}`")
        elif target == "suts":
            tcs = suts_tcs.get(fn) or []
            lines.append("")
            lines.append("**SUTS 기존 TC:**")
            if tcs:
                lines.append(f"- TC 목록: `{', '.join(tcs[:12])}{'...' if len(tcs) > 12 else ''}`")
                lines.append(f"- TC 수: `{len(tcs)}`")
            else:
                lines.append("- 기존 TC 없음 또는 문서 미연결 (새로 작성 필요)")
        elif target == "sits":
            chains = sits_chains.get(fn) or []
            if src_calls:
                lines.append("")
                lines.append("**통합 호출 관계 (소스 기준):**")
                for callee in src_calls[:6]:
                    lines.append(f"- `{fn}` → `{callee}`")
            if chains:
                lines.append("")
                lines.append("**SITS 기존 Call Chain (링크 문서):**")
                for chain in chains[:5]:
                    lines.append(f"- {chain}")
                if len(chains) > 5:
                    lines.append(f"- ... 외 {len(chains) - 5}개")

        # ── Change-type-specific update guidance ───────────────────────────
        lines.append("")
        lines.append(f"**{kind} 변경 시 검토 항목:**")
        if target == "uds":
            if kind == "BODY":
                lines.append("- UDS 기능 설명(description) 섹션: 내부 동작/로직 변경 반영")
                lines.append("- outputs 필드: 반환값·출력 범위 변경 여부 확인")
                if src_calls:
                    lines.append(f"- calls_list 섹션: 호출 함수 추가/제거 반영")
            elif kind in ("SIGNATURE", "HEADER"):
                lines.append("- inputs 필드: 파라미터 추가·삭제·타입 변경 반영")
                lines.append("- outputs 필드: 반환 타입 변경 반영")
                lines.append("- 인터페이스 계약(interface contract) 섹션 전면 검토")
            lines.append("- ASIL 등급 유지 여부 확인")
            if src_req_ids:
                lines.append(f"- 요구사항 링크 유효성 확인: `{', '.join(src_req_ids[:6])}`")
        elif target == "suts":
            if kind == "BODY":
                lines.append("- 기존 TC의 Expected 값 재검토 (동작 변경 시 실패 예상)")
                lines.append("- 새로운 실행 경로·분기 조건에 대한 TC 추가 여부 확인")
            elif kind in ("SIGNATURE", "HEADER"):
                lines.append("- TC 입력 파라미터 정의 변경 필요 (시그니처 변경)")
                lines.append("- 파라미터 추가 시: 새 입력값 경계 TC 추가")
                lines.append("- 파라미터 삭제 시: 해당 TC 삭제 또는 수정")
            lines.append("- 삭제된 함수인 경우 연관 TC 전체 제거")
        elif target == "sits":
            if kind == "BODY":
                lines.append("- 통합 TC 시퀀스의 Expected 결과 재검토")
                lines.append("- 호출 순서·조건 변경 시 Call Chain TC 시퀀스 수정")
            elif kind in ("SIGNATURE", "HEADER"):
                lines.append("- Entry point 파라미터 변경 → 통합 TC 입력값 업데이트")
                lines.append("- 인터페이스 변경 시 모든 연관 통합 시나리오 재검토")
        elif target == "sts":
            if kind == "BODY":
                lines.append("- 요구사항 Pass/Fail 기준에 영향을 주는 동작 변경 확인")
                lines.append("- 기존 STS TC Expected 결과 재확인")
            elif kind in ("SIGNATURE", "HEADER"):
                lines.append("- 시그니처 변경 → 관련 TC 입력 인터페이스 업데이트")
                lines.append("- 삭제/추가된 파라미터에 해당하는 TC 추가/제거")
            if src_req_ids:
                lines.append(f"- 트레이서빌리티 확인 대상: `{', '.join(src_req_ids[:6])}`")
        else:
            lines.append("- 모듈/인터페이스 설명이 변경 내용과 일치하는지 확인")

    # --- Review Checklist summary ---
    lines.extend(["", "## Review Checklist"])
    if target == "uds":
        lines.append("- [ ] 위 각 함수의 UDS 스펙 설명(description)이 변경 내용을 반영하는가?")
        if is_signature or is_header:
            lines.append("- [ ] inputs/outputs 인터페이스 정의가 새 시그니처와 일치하는가?")
        lines.append("- [ ] ASIL 등급이 변경된 동작 범위와 일치하는가?")
        lines.append("- [ ] 관련 요구사항(SwTR/SwFn) 링크가 유효한가?")
        lines.append("- [ ] calls_list (호출 함수 목록)이 최신 소스와 일치하는가?")
    elif target == "suts":
        lines.append("- [ ] 위 기존 TC의 예상 결과가 변경된 동작에 맞게 갱신되었는가?")
        if is_signature or is_header:
            lines.append("- [ ] TC 입력 파라미터 정의가 새 시그니처와 일치하는가?")
        lines.append("- [ ] 새로운 실행 경로를 커버하는 TC가 추가되었는가?")
        lines.append("- [ ] 삭제된 함수에 해당하는 TC가 제거되었는가?")
    elif target == "sits":
        lines.append("- [ ] 위 Call Chain을 포함하는 통합 TC 시퀀스가 유효한가?")
        lines.append("- [ ] 변경된 함수와 하위 모듈의 인터페이스 계약이 유지되는가?")
        if is_signature or is_header:
            lines.append("- [ ] 통합 TC의 entry point 파라미터가 새 시그니처와 일치하는가?")
    elif target == "sts":
        lines.append("- [ ] 변경된 함수와 연결된 요구사항 트레이서빌리티가 유효한가?")
        lines.append("- [ ] 변경된 동작이 기존 Pass/Fail 기준을 무효화하는가?")
        if is_signature or is_header:
            lines.append("- [ ] 시그니처 변경으로 인해 추가/삭제해야 할 TC가 있는가?")
    else:
        lines.extend(
            [
                "- [ ] 모듈/인터페이스 설명이 헤더/소스 변경과 일치하는가?",
                "- [ ] 아키텍처 파티션 영향이 문서화되었는가?",
            ]
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out_path)


def _run_uds_generation(trigger: ChangeTrigger) -> Dict[str, Any]:
    out_dir = REPO_ROOT / "backend" / "reports" / "uds_local"
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {p.resolve() for p in out_dir.glob("uds_spec_generated_expanded_*.docx")}
    env = os.environ.copy()
    env["UDS_CHANGED_FILES"] = ",".join(trigger.changed_files)
    env["UDS_IMPACT_MODE"] = "1"
    env["UDS_SOURCE_ROOT"] = str(trigger.source_root or "")
    cmd = [sys.executable, str(REPO_ROOT / "tools" / "generate_uds_local.py")]
    run = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )
    if run.returncode != 0:
        err = ((run.stderr or "") + "\n" + (run.stdout or "")).strip()[-4000:]
        raise RuntimeError(f"UDS regeneration failed: {err}")
    candidates = [p.resolve() for p in out_dir.glob("uds_spec_generated_expanded_*.docx")]
    new_files = [p for p in candidates if p not in before]
    chosen = max(new_files or candidates, key=lambda p: p.stat().st_mtime)
    return {"output_path": str(chosen), "stdout_tail": (run.stdout or "")[-1000:]}


def _run_suts_generation(entry: Any, target_functions: List[str] | None = None) -> Dict[str, Any]:
    from suts_generator import generate_suts

    source_root = str(entry.source_root or "").strip()
    if not source_root:
        raise RuntimeError("SUTS regeneration requires source_root")
    out_dir = REPO_ROOT / "reports" / "suts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"suts_impact_{_ts()}.xlsm"
    template_path = _resolve_existing(entry.linked_docs.suts) or _discover_doc("suts", {".xlsm", ".xlsx"})
    srs_path = _resolve_existing(entry.linked_docs.srs) or _discover_doc("srs", {".docx"})
    sds_path = _resolve_existing(entry.linked_docs.sds) or _discover_doc("sds", {".docx"})
    uds_path = _resolve_existing(entry.linked_docs.uds)
    hsis_path = _resolve_existing(entry.linked_docs.hsis) or _discover_doc("hsis", {".xlsx", ".xlsm"})

    result = generate_suts(
        source_root=source_root,
        output_path=str(out_path),
        template_path=template_path,
        project_config={
            "project_id": str(entry.id or "PROJECT").upper(),
            "doc_id": f"{str(entry.id or 'PROJECT').upper()}-SUTS",
            "version": "impact",
            "asil_level": "",
        },
        srs_docx_path=srs_path,
        sds_docx_path=sds_path,
        uds_path=uds_path,
        hsis_path=hsis_path,
        target_function_names=list(target_functions or []),
    )
    return {
        "output_path": str(out_path),
        "test_case_count": result.get("test_case_count", 0),
        "validation_report_path": result.get("validation_report_path", ""),
    }


def _run_sits_generation(entry: Any) -> Dict[str, Any]:
    """Regenerate SITS for the given registry entry.

    Unlike SUTS (which can be scoped to specific functions), SITS always
    regenerates the full integration test spec because cross-module call
    flows span the entire codebase.
    """
    from sits_generator import generate_sits

    source_root = str(entry.source_root or "").strip()
    if not source_root:
        raise RuntimeError("SITS regeneration requires source_root")
    out_dir = REPO_ROOT / "reports" / "sits"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"sits_impact_{_ts()}.xlsm"
    template_path = _resolve_existing(entry.linked_docs.sits) or _discover_doc("sits", {".xlsm", ".xlsx"})
    srs_path = _resolve_existing(entry.linked_docs.srs) or _discover_doc("srs", {".docx"})
    sds_path = _resolve_existing(entry.linked_docs.sds) or _discover_doc("sds", {".docx"})
    uds_path = _resolve_existing(entry.linked_docs.uds)
    hsis_path = _resolve_existing(entry.linked_docs.hsis) or _discover_doc("hsis", {".xlsx", ".xlsm"})
    stp_path = _discover_doc("stp", {".docx", ".pdf", ".txt"})

    result = generate_sits(
        source_root=source_root,
        output_path=str(out_path),
        template_path=template_path,
        project_config={
            "project_id": str(entry.id or "PROJECT").upper(),
            "doc_id": f"{str(entry.id or 'PROJECT').upper()}-SITS",
            "version": "impact",
            "asil_level": "",
        },
        srs_docx_path=srs_path,
        sds_docx_path=sds_path,
        uds_path=uds_path,
        hsis_path=hsis_path,
        stp_path=stp_path,
    )
    return {
        "output_path": str(out_path),
        "test_case_count": result.get("test_case_count", 0),
        "total_sub_cases": result.get("total_sub_cases", 0),
        "validation_report_path": result.get("validation_report_path", ""),
    }


def _execute_auto_action(target: str, trigger: ChangeTrigger, entry: Any, target_functions: List[str] | None = None) -> Dict[str, Any]:
    if target == "uds":
        return _run_uds_generation(trigger)
    if target == "suts":
        return _run_suts_generation(entry, target_functions)
    if target == "sits":
        return _run_sits_generation(entry)
    raise RuntimeError(f"unsupported AUTO target: {target}")


def _module_name(info: Dict[str, Any]) -> str:
    module = str(info.get("module_name") or "").strip()
    if module:
        return module.lower()
    file_path = str(info.get("file") or "").strip()
    if not file_path:
        return ""
    return Path(file_path).parent.name.lower()


def _build_neighbors(
    call_map: Dict[str, List[str]],
    by_name: Dict[str, Dict[str, Any]],
    *,
    same_module_only: bool,
) -> Dict[str, Set[str]]:
    neighbors: Dict[str, Set[str]] = {}
    for caller, raw_callees in (call_map or {}).items():
        caller_key = str(caller or "").strip().lower()
        if not caller_key:
            continue
        caller_info = by_name.get(caller_key) or {}
        caller_module = _module_name(caller_info)
        for callee in raw_callees or []:
            callee_key = str(callee or "").strip().lower()
            if not callee_key:
                continue
            callee_info = by_name.get(callee_key) or {}
            if same_module_only and caller_module and _module_name(callee_info) and caller_module != _module_name(callee_info):
                continue
            neighbors.setdefault(caller_key, set()).add(callee_key)
            neighbors.setdefault(callee_key, set()).add(caller_key)
    return neighbors


def _hop_limited_impact(
    seeds: Set[str],
    neighbors: Dict[str, Set[str]],
    *,
    max_hop: int,
    max_impacted_functions: int,
) -> Dict[str, List[str]]:
    direct = sorted(seeds)
    if not seeds:
        return {"direct": [], "indirect_1hop": [], "indirect_2hop": []}

    visited = set(seeds)
    frontier = set(seeds)
    indirect_1: Set[str] = set()
    indirect_2: Set[str] = set()

    for depth in range(1, max_hop + 1):
        next_frontier: Set[str] = set()
        for func in frontier:
            for neighbor in neighbors.get(func, set()):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                next_frontier.add(neighbor)
                if depth == 1:
                    indirect_1.add(neighbor)
                elif depth == 2:
                    indirect_2.add(neighbor)
        if len(visited) > max_impacted_functions:
            break
        frontier = next_frontier
        if not frontier:
            break

    return {
        "direct": sorted(direct),
        "indirect_1hop": sorted(indirect_1),
        "indirect_2hop": sorted(indirect_2),
    }


def _selected_targets(targets: Iterable[str] | None) -> List[str]:
    values = [str(x or "").strip().lower() for x in (targets or []) if str(x or "").strip()]
    return sorted(dict.fromkeys(values)) if values else ["sds", "sits", "sts", "suts", "uds"]


def _fallback_changed_types_from_files(changed_files: List[str]) -> Dict[str, str]:
    inferred: Dict[str, str] = {}
    for path_text in changed_files:
        name = Path(str(path_text or "").strip()).stem
        if not name:
            continue
        kind = "HEADER" if str(path_text).lower().endswith(".h") else "BODY"
        inferred[name.lower()] = kind
    return inferred


def _resolve_changed_types_to_functions(
    changed_types: Dict[str, str],
    changed_files: List[str],
    by_name: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    if not changed_types or not by_name:
        return changed_types
    resolved: Dict[str, str] = {}
    for path_text in changed_files:
        raw = str(path_text or "").strip()
        if not raw:
            continue
        kind = "HEADER" if raw.lower().endswith(".h") else "BODY"
        raw_norm = raw.replace("\\", "/").lower()
        raw_name = Path(raw_norm).name
        for func_name, info in by_name.items():
            file_path = str(info.get("file") or "").replace("\\", "/").lower()
            if not file_path:
                continue
            if file_path.endswith(raw_norm) or file_path.endswith(raw_name):
                resolved[func_name] = kind
    return resolved or changed_types


def _action_for_target(target: str, changed_types: Dict[str, str], changed_files: List[str]) -> str:
    decision = "-"
    for change_type in changed_types.values():
        action = ACTION_MATRIX.get(change_type, {}).get(target, "-")
        if action == "FLAG":
            decision = "FLAG"
        elif action == "AUTO" and decision == "-":
            decision = "AUTO"
    if target in {"sts", "sds"} and any(str(path).lower().endswith(".h") for path in changed_files):
        decision = "FLAG"
    return decision


def _summarize_actions(
    targets: List[str],
    changed_types: Dict[str, str],
    changed_files: List[str],
    impact_groups: Dict[str, List[str]],
    *,
    auto_generate: bool = False,
) -> Dict[str, Dict[str, Any]]:
    impacted_all = set(impact_groups.get("direct", [])) | set(impact_groups.get("indirect_1hop", [])) | set(impact_groups.get("indirect_2hop", []))
    changed_direct = set(impact_groups.get("direct", []))
    actions: Dict[str, Dict[str, Any]] = {}
    for target in targets:
        decision = _action_for_target(target, changed_types, changed_files)
        # Downgrade AUTO → FLAG when auto_generate is disabled
        if decision == "AUTO" and not auto_generate:
            decision = "FLAG"
        if decision == "AUTO":
            funcs = sorted(impacted_all if target in AUTO_DOCS else changed_direct)
            actions[target] = {
                "mode": "AUTO",
                "status": "planned",
                "function_count": len(funcs),
                "functions": funcs,
            }
        elif decision == "FLAG":
            funcs = sorted(changed_direct or impacted_all)
            actions[target] = {
                "mode": "FLAG",
                "status": "review_required",
                "function_count": len(funcs),
                "functions": funcs,
            }
        else:
            actions[target] = {
                "mode": "-",
                "status": "skipped",
                "function_count": 0,
                "functions": [],
            }
    return actions


def run_impact_update(
    trigger: ChangeTrigger,
    *,
    options: ImpactOptions | None = None,
    on_progress: Any | None = None,
) -> Dict[str, Any]:
    options = options or ImpactOptions()
    targets = _selected_targets(trigger.targets)
    if callable(on_progress):
        on_progress("prepare", "실행 준비 중입니다.", {"changed_files": len(trigger.changed_files or [])})
    lock = acquire_run_lock(trigger.scm_id)
    if not lock.get("ok"):
        return {"ok": False, "reason": lock.get("reason"), "lock": lock}

    try:
        entry = get_registry_entry(trigger.scm_id)
        previous_linked_docs = entry.linked_docs.model_dump(mode="json") if entry else {}
        if callable(on_progress):
            on_progress("classify", "변경 함수를 분류 중입니다.", {"changed_files": len(trigger.changed_files or [])})
        changed_types = classify_changed_functions(
            trigger.source_root,
            trigger.changed_files,
            scm_type=trigger.scm_type,
            base_ref=trigger.base_ref,
        )
        if not changed_types and trigger.changed_files:
            changed_types = _fallback_changed_types_from_files(trigger.changed_files)

        if entry and entry.source_root:
            if callable(on_progress):
                on_progress("impact_analysis", "영향 범위를 계산 중입니다.", {"changed_functions": len(changed_types)})
            sections = _load_source_sections(entry.source_root)
            by_name_raw = sections.get("function_details_by_name", {}) or {}
            by_name = {str(k).strip().lower(): v for k, v in by_name_raw.items() if isinstance(v, dict)}
            changed_types = _resolve_changed_types_to_functions(changed_types, trigger.changed_files, by_name)
            neighbors = _build_neighbors(
                sections.get("call_map", {}) or {},
                by_name,
                same_module_only=options.same_module_only,
            )
        else:
            by_name = {}
            neighbors = {}

        impact_groups = _hop_limited_impact(
            set(changed_types),
            neighbors,
            max_hop=options.max_hop,
            max_impacted_functions=options.max_impacted_functions,
        )
        impacted_total = len(set(impact_groups["direct"]) | set(impact_groups["indirect_1hop"]) | set(impact_groups["indirect_2hop"]))
        warnings: List[str] = []
        if impacted_total > options.max_impacted_functions:
            warnings.append(
                f"impacted function count exceeded limit ({impacted_total}>{options.max_impacted_functions}); promote to review"
            )
        actions = _summarize_actions(targets, changed_types, trigger.changed_files, impact_groups, auto_generate=bool(trigger.auto_generate))
        if warnings:
            for target, info in actions.items():
                if info.get("mode") == "AUTO":
                    info["mode"] = "FLAG"
                    info["status"] = "review_required"

        result = {
            "ok": True,
            "dry_run": bool(trigger.dry_run),
            "trigger": trigger.to_dict(),
            "changed_function_types": dict(sorted(changed_types.items())),
            "impact": impact_groups,
            "warnings": warnings,
            "actions": actions,
        }
        if not trigger.dry_run:
            linked_docs = entry.linked_docs if entry else ScmLinkedDocs()
            if callable(on_progress):
                on_progress(
                    "execute_actions",
                    "문서 액션을 실행 중입니다.",
                    {"impacted_functions": impacted_total, "targets": len(actions)},
                )
            action_items = list(actions.items())
            total_actions = len(action_items)
            for idx, (target, info) in enumerate(action_items, start=1):
                if info.get("mode") == "AUTO":
                    if callable(on_progress):
                        on_progress(
                            "execute_actions",
                            f"{target.upper()} 자동 갱신을 실행 중입니다. ({idx}/{total_actions})",
                            {
                                "impacted_functions": impacted_total,
                                "targets": total_actions,
                                "current_target": target,
                                "current_index": idx,
                            },
                        )
                    try:
                        exec_result = _execute_auto_action(
                            target,
                            trigger,
                            entry,
                            info.get("functions") or [],
                        )
                        info["status"] = "completed"
                        info["output_path"] = exec_result.get("output_path", "")
                        info["result"] = exec_result
                        if info["output_path"] and entry:
                            _update_linked_doc(entry.id, target, info["output_path"])
                    except Exception as exc:
                        info["status"] = "failed"
                        info["error"] = str(exc)
                        result["ok"] = False
                elif info.get("mode") == "FLAG":
                    if callable(on_progress):
                        on_progress(
                            "execute_actions",
                            f"{target.upper()} 검토 아티팩트를 생성 중입니다. ({idx}/{total_actions})",
                            {
                                "impacted_functions": impacted_total,
                                "targets": total_actions,
                                "current_target": target,
                                "current_index": idx,
                            },
                        )
                    artifact_path = _write_review_artifact(
                        target,
                        trigger,
                        changed_types,
                        impact_groups,
                        by_name,
                        getattr(linked_docs, target, ""),
                    )
                    info["artifact_path"] = artifact_path
        if callable(on_progress):
            on_progress("write_audit", "실행 이력을 저장 중입니다.", {"targets": len(actions)})
        audit_payload = {
            "scm_id": trigger.scm_id,
            "trigger": trigger.trigger_type,
            "changed_files": trigger.changed_files,
            "changed_functions": dict(sorted(changed_types.items())),
            "impacted_functions": impact_groups,
            "targets": targets,
            "dry_run": bool(trigger.dry_run),
            "warnings": warnings,
            "actions": actions,
        }
        audit_path = write_impact_audit(audit_payload)
        change_log = build_change_log(
            run_id=audit_path.stem,
            trigger=trigger.to_dict(),
            result=result,
            previous_linked_docs=previous_linked_docs,
        )
        change_log_path = write_change_log(change_log)
        result["audit_path"] = str(audit_path)
        result["change_log"] = {
            "path": str(change_log_path),
            "run_id": str(change_log.get("run_id") or audit_path.stem),
            "summary": change_log.get("summary") or {},
        }
        if callable(on_progress):
            on_progress("done", "완료되었습니다.", {"targets": len(actions)})
        return result
    finally:
        release_run_lock()
