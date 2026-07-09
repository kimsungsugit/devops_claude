from __future__ import annotations

import logging
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


logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTO_DOCS = {"uds", "suts", "sits"}
FLAG_DOCS = {"sts", "sds"}

# ISO 26262 증거 보강: ASIL 등급 순위 + 등급별 구조 커버리지 타깃(Part 6 Table 9/12 권고).
_ASIL_RANK = {"QM": 0, "A": 1, "B": 2, "C": 3, "D": 4}
_COVERAGE_TARGET = {
    "D": "MC/DC", "C": "분기(branch)", "B": "분기(branch)",
    "A": "구문(statement)", "QM": "구문(statement)",
}
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
    # impact도 preprocess=True(정밀)로 파싱한다(안전 우선, ISO 26262). preprocess=False는 gcc
    # 전처리를 생략해 빠르지만 (1) 함수형 매크로로 가려진 호출 엣지를 놓쳐 영향 함수를 '과소보고'
    # (진짜 영향받은 안전 함수를 재검증 대상에서 누락 — unsafe 방향)하고, (2) #ifdef 가드 동일
    # 함수명 변형을 둘 다 파싱해 first-wins ASIL 오판 위험이 있다. 속도는 regex hot-loop 제거 +
    # 디스크 캐시(동일 소스 재실행 시 파싱 skip)로 확보하며, 문서생성과 동일 정밀·동일 캐시 tier를 쓴다.
    try:
        from backend.helpers import _get_source_sections_cached

        return _get_source_sections_cached(source_root, preprocess=True)
    except Exception:
        import report_generator as rg

        return rg.generate_uds_source_sections(source_root, preprocess=True)


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
    if not _safe_exists(payload_path):
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


def _safe_exists(path: Path) -> bool:
    """Path.exists()의 예외 안전판. cloudium U:\\(SMB) 등 접근 거부 경로는 exists()가
    False가 아니라 PermissionError(WinError 5)/OSError를 던질 수 있다 — 이 예외가 잡히지
    않으면 best-effort 문서 읽기가 핵심 영향분석 전체를 500으로 죽인다. 예외는 '없음'으로 처리."""
    try:
        return path.exists()
    except Exception:
        return False


def _load_uds_fn_details(
    linked_doc: str, flagged_fns: List[str]
) -> Dict[str, Dict[str, Any]]:
    """Load UDS spec fields per flagged function from the payload sidecar."""
    if not linked_doc:
        return {}
    payload_path = Path(linked_doc).with_suffix(".payload.json")
    if not _safe_exists(payload_path):
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


# 링크된 UDS 문서에서 추출한 {함수명(소문자): ASIL} 맵의 경로 캐시.
# 대형 SwUDS docx(수십MB)를 매 impact 실행마다 워커 IPC로 재-read/재파싱하지 않도록 1회만.
# 키는 문서 경로(파일명에 버전 포함이라 개정 시 경로가 바뀜 → staleness 위험 낮음).
_UDS_NAME_ASIL_CACHE: Dict[str, Dict[str, str]] = {}


def _uds_name_asil_map(uds_path: str) -> Dict[str, str]:
    """링크된 UDS(SwUDS) 문서에서 {함수명(소문자): ASIL} 맵을 추출한다.

    C 소스에 Doxygen `@asil` 주석이 없는 프로젝트(예: NE1AW_PORTING)는 함수 ASIL이 전부
    '미상'이 되는데, 실제 등급은 UDS 문서에 있다. UDS는 cloudium U:\\일 수 있으므로 반드시
    워커(`get_resolver().read_bytes`) 경유로 읽는다(직접 접근 금지). heading 기반 파서
    (`parse_swuds_docx`)를 우선하고, heading-less 레이아웃은 reverse-corpus 추출기로 보완.
    접근 불가/미존재/파싱 실패는 빈 맵으로 조용히 폴백(impact 본류 비차단). 경로 캐시.
    """
    if not uds_path:
        return {}
    _cached = _UDS_NAME_ASIL_CACHE.get(uds_path)
    if _cached is not None:
        return _cached
    try:
        from backend.services.file_resolver import get_resolver
        docx_bytes = get_resolver().read_bytes(uds_path)
    except FileNotFoundError:
        _UDS_NAME_ASIL_CACHE[uds_path] = {}  # 진짜 부재 → 빈 맵 캐시(재파싱 회피)
        return {}
    except (PermissionError, OSError):
        # ⚠ 워커 미기동/네트워크 블립을 read_bytes가 PermissionError/OSError로 던진다
        # (file_resolver _ipc_call/_ensure_gate). 이걸 캐시하면 워커가 나중에 떠도 세션 내내
        # 미보강(ASIL 안전게이트 무력화) → 캐시하지 않고 다음 impact 실행서 재시도한다.
        return {}
    except Exception:
        return {}  # 기타 일시 오류도 캐시 안 함
    result: Dict[str, str] = {}
    if docx_bytes:
        # 1) heading 기반 SwUDS 파서 — 함수명→ASIL 직접(현대/모비스 포맷).
        try:
            from backend.services.swut_swuds_parser import parse_swuds_docx
            _res = parse_swuds_docx(docx_bytes)
            for _e in (_res.entries or []):
                _n = str(getattr(_e, "name", "") or "").strip().lower()
                _a = str(getattr(_e, "asil", "") or "").strip()
                if _n and _a:
                    result.setdefault(_n, _a)
        except Exception:
            pass
        # 2) heading-less 레이아웃 폴백 — heading 파서가 거의 못 뽑을 때만(v1.07류). reverse-corpus는
        #    자유 텍스트 근접매칭이라 프로즈를 함수명으로 오포착(false-positive→오등급 하향 위험)할 수 있고
        #    36MB docx를 2회 더 파싱하므로, heading 파서가 구조화 표에서 신뢰성 있게 뽑으면 쓰지 않는다.
        if len(result) < 5:
            try:
                from backend.services.iso26262_doc_asil_extractor import (
                    extract_function_asil_from_suds,
                    extract_function_name_to_swufn_from_suds,
                )
                _swufn_asil = extract_function_asil_from_suds(docx_bytes) or {}
                _name_swufn = extract_function_name_to_swufn_from_suds(docx_bytes) or {}
                for _n, _s in _name_swufn.items():
                    _a = _swufn_asil.get(_s)
                    _nl = str(_n or "").strip().lower()
                    if _nl and _a:
                        result.setdefault(_nl, _a)
            except Exception:
                pass
    _UDS_NAME_ASIL_CACHE[uds_path] = result
    return result


def _is_blank_asil(value: Any) -> bool:
    """ASIL이 '미상'인지 판정. ⚠ uds_generator는 소스/문서에 ASIL이 없으면 빈 문자열이 아니라
    placeholder 'TBD'를 넣는다(report_gen/uds_generator.py:1126) — 빈 문자열만 검사하면 실제
    미태그 함수(예: NE1AW의 497개)를 전부 놓쳐 보강이 no-op가 된다. helpers/uds._is_blank_value와 동일 집합."""
    return str(value or "").strip().upper() in ("", "TBD", "N/A", "-", "UNKNOWN")


def _enrich_asil_from_uds(by_name: Dict[str, Any], uds_path: str) -> tuple[int, int]:
    """소스 주석에 ASIL이 없는 함수만 링크된 UDS의 함수별 ASIL로 보강한다(안전측: 소스 > UDS).

    소스 주석 ASIL이 있는 함수는 절대 덮지 않는다. 보강된 함수엔 `asil_source="uds"` 표식.
    반환: (보강한 함수 수, 보강 후에도 남은 미상 수).
    """
    if not uds_path or not isinstance(by_name, dict):
        return 0, 0
    missing = [
        fn for fn, info in by_name.items()
        if isinstance(info, dict) and _is_blank_asil(info.get("asil"))
    ]
    if not missing:
        return 0, 0
    name_asil = _uds_name_asil_map(uds_path)
    if not name_asil:
        return 0, len(missing)
    enriched = 0
    for fn in missing:
        _a = name_asil.get(fn)
        if _a:
            by_name[fn]["asil"] = _a
            by_name[fn]["asil_source"] = "uds"
            enriched += 1
    return enriched, len(missing) - enriched


def _load_suts_fn_tcs(
    linked_doc: str, flagged_fns: List[str]
) -> Dict[str, List[str]]:
    """Return {fn_name: [tc_id, ...]} by parsing the existing SUTS xlsm.
    Falls back to empty dict on any error (file missing, parse failure, etc.)."""
    if not linked_doc or not _safe_exists(Path(linked_doc)):
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
    """Return {entry_fn: [label, ...]} from the SITS vectorcast intermediate JSON.
    Falls back to empty dict on any error (missing/inaccessible file — cloudium U:\\ 등)."""
    if not linked_doc:
        return {}
    try:
        stem = Path(linked_doc).stem
        intermediate = Path(linked_doc).with_name(stem + "_vectorcast.json")
        if not _safe_exists(intermediate):
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
    except Exception:
        return {}


def _write_review_artifact(
    target: str,
    trigger: ChangeTrigger,
    changed_types: Dict[str, str],
    impact_groups: Dict[str, List[str]],
    by_name: Dict[str, Dict[str, Any]] | None = None,
    linked_doc: str = "",
    ai_guide: Any = None,
    *,
    pre_uds_details: Dict[str, Any] | None = None,
    pre_suts_tcs: Dict[str, Any] | None = None,
    pre_sits_chains: Dict[str, Any] | None = None,
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
    # Load document-specific data (best-effort; empty dict if linked_doc missing).
    # run 스코프 사전로드(pre_*)가 주어지면 재파싱을 회피한다 — FLAG 타깃 루프가 매 반복마다
    # 동일 인자로 대형 SUTS xlsm을 재파싱하던 중복 제거. 미제공(None) 시 종전대로 매칭 타깃만 로드.
    uds_doc_details: Dict[str, Any] = (
        pre_uds_details if pre_uds_details is not None
        else (_load_uds_fn_details(linked_doc, flagged_fns) if target == "uds" else {})
    )
    suts_tcs: Dict[str, Any] = (
        pre_suts_tcs if pre_suts_tcs is not None
        else (_load_suts_fn_tcs(linked_doc, flagged_fns) if target == "suts" else {})
    )
    sits_chains: Dict[str, Any] = (
        pre_sits_chains if pre_sits_chains is not None
        else (_load_sits_fn_chains(linked_doc, flagged_fns) if target == "sits" else {})
    )

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
    # --- AI Guide sections (if available) ---
    if ai_guide is not None:
        guide = ai_guide.to_dict() if hasattr(ai_guide, "to_dict") else ai_guide
        lines.extend(["", "---", "", "## AI Impact Guide"])
        risk = guide.get("risk") or {}
        if risk:
            lines.append(f"**리스크 등급**: {risk.get('grade', '-')} (점수: {risk.get('score', '-')}/100)")
            lines.append(f"**ASIL 에스컬레이션**: {'예' if risk.get('asil_escalation') else '아니오'}")
            if risk.get("justification"):
                lines.append(f"**근거**: {risk['justification']}")
        summary = guide.get("executive_summary", "")
        if summary:
            lines.extend(["", "### Executive Summary", "", summary])
        cross_doc = guide.get("cross_doc_impacts") or {}
        if cross_doc:
            lines.extend(["", "### Cross-Document Impact"])
            for doc_type, impacts in cross_doc.items():
                lines.append(f"\n**{doc_type.upper()}**:")
                for imp in impacts[:5]:
                    lines.append(f"- {imp}")
        checklist_ai = guide.get("review_checklist") or []
        if checklist_ai:
            lines.extend(["", "### AI Review Checklist"])
            for item in checklist_ai:
                lines.append(f"- [{item.get('priority', '-')}] {item.get('item', '')}")
        test_recs = guide.get("test_recommendations") or []
        if test_recs:
            lines.extend(["", "### Test Recommendations"])
            for rec in test_recs[:10]:
                lines.append(f"- **{rec.get('function', '?')}** ({rec.get('test_type', '')}): {rec.get('description', '')}")
        ai_flag = "AI-enriched" if guide.get("ai_enriched") else "deterministic"
        lines.append(f"\n> Generated: {guide.get('generated_at', '')} ({ai_flag})")

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
    edit_types: Dict[str, str] | None = None,
) -> Dict[str, str]:
    if not changed_types or not by_name:
        return changed_types
    # classify가 함수명으로 분류한 정밀 kind(SIGNATURE/NEW/DELETE/VARIABLE 등)를 보존한다.
    # (대소문자 무시 — by_name 키는 소문자, classify 키는 원본 케이스일 수 있음.)
    ct_lower = {str(k).strip().lower(): v for k, v in changed_types.items()}
    # Jenkins changeSet editType(파일경로→add/edit/delete) — 로컬 diff 불가(cloudium/원격)
    # 시 해당 파일 함수들의 기본 kind를 확장자(BODY/HEADER) 대신 NEW/DELETE로 격상한다.
    et_norm = {
        str(k).replace("\\", "/").strip().lower(): str(v or "").strip().lower()
        for k, v in (edit_types or {}).items()
    }
    # by_name의 파일경로 정규화를 1회만 선계산한다 — 과거엔 변경파일마다 전체 함수의 file 경로를
    # str/replace/lower로 재정규화(O(F·N) 문자열 연산)했다. endswith 매칭 자체는 동일 문자열에
    # 대해 그대로 수행하므로 결과 시맨틱은 완전히 불변(성능만 개선).
    norm_files = [
        (func_name, str(info.get("file") or "").replace("\\", "/").lower())
        for func_name, info in by_name.items()
    ]
    norm_files = [(fn, fp) for fn, fp in norm_files if fp]
    resolved: Dict[str, str] = {}
    for path_text in changed_files:
        raw = str(path_text or "").strip()
        if not raw:
            continue
        ext_kind = "HEADER" if raw.lower().endswith(".h") else "BODY"
        raw_norm = raw.replace("\\", "/").lower()
        raw_name = Path(raw_norm).name
        # editType이 있으면 그 파일 함수의 기본 kind를 editType으로(add→NEW/delete→DELETE).
        # func별 정밀 kind(로컬 diff)가 있으면 그쪽이 우선(아래 ct_lower.get).
        _et = et_norm.get(raw_norm)
        if _et == "add":
            file_default = "NEW"
        elif _et == "delete":
            file_default = "DELETE"
        else:
            file_default = ext_kind
        # 1차: 전체 상대경로(raw_norm) endswith — 정확. 2차: 그 파일에 1차 매칭이 전무할 때만
        # basename(raw_name) 폴백 — 동명 파일이 여러 모듈에 있을 때의 과대 매칭을 줄인다.
        full_hits: Dict[str, str] = {}
        base_hits: Dict[str, str] = {}
        for func_name, file_path in norm_files:
            # 함수별 정밀 kind가 있으면 그것을, 없으면 파일 editType/확장자 기반 기본값.
            kind = ct_lower.get(func_name, file_default)
            if file_path.endswith(raw_norm):
                full_hits[func_name] = kind
            elif file_path.endswith(raw_name):
                base_hits[func_name] = kind
        resolved.update(full_hits or base_hits)
    # DELETE 등 현재 소스(by_name)에 더는 존재하지 않는 함수(삭제됨)는 위 file-매칭으로 잡히지
    # 않으므로 명시 보존한다 — 그래야 SUTS/SITS의 '삭제 TC 제거' 가이드가 트리거된다.
    for fn, kind in ct_lower.items():
        if kind == "DELETE" and fn not in resolved:
            resolved[fn] = kind
    return resolved or changed_types


def _collect_signature_changes(trigger, meta, entry) -> Dict[str, Dict[str, str]]:
    """함수별 시그니처 이전/이후 선언 원문을 추출한다(UI '변경 상세' 원문 표시용).

    - svn revision-range(baseline A ↔ build B): `svn diff -r A:B <scm_url>` 전체 unified diff 1회.
    - 로컬 git/svn working-copy: 변경 파일별 unified diff(상한 60개).
    best-effort — 실패/미지원이면 빈 dict(영향 분석 자체엔 무영향, UI 원문만 미표시).
    """
    from workflow.delta_update import extract_signature_changes
    meta = meta or {}
    base_rev = str(meta.get("baseline_revision") or "").strip()
    build_rev = str(meta.get("build_revision") or "").strip()
    scm_url = str(getattr(entry, "scm_url", "") or "").strip()
    # (1) svn revision-range: 전체 unified diff 1회 (baseline A ↔ build B 정밀 델타)
    if base_rev.isdigit() and build_rev.isdigit() and scm_url:
        # A>B(로컬 작업본이 선택 빌드보다 최신)면 svn diff -r A:B가 역방향 델타를 내
        # NEW/DELETE·before/after가 뒤집힌다 → 원문 보강 생략(정직한 미표시).
        if int(base_rev) > int(build_rev):
            return {}
        try:
            from backend.services.local_service import svn_diff_unified
            from backend.services.scm_registry import resolve_scm_credentials
            _user, _pw, _ = resolve_scm_credentials(scm_id=trigger.scm_id)
            d = svn_diff_unified(
                repo_url=scm_url, rev_a=base_rev, rev_b=build_rev,
                username=_user, password=_pw,
            )
            if int(d.get("rc", 1)) == 0:
                return extract_signature_changes(d.get("output") or "")
        except Exception as exc:  # noqa: BLE001 — best-effort, 실패 흡수
            logger.debug("svn_diff_unified signature extraction failed: %s", exc)
        return {}
    # (2) 로컬 git/svn working-copy diff: 변경 파일별(상한, 파일 단위 격리)
    src = str(getattr(entry, "source_root", "") or getattr(trigger, "source_root", "") or "").strip()
    scm_type = str(getattr(trigger, "scm_type", "") or "").lower()
    changed_files = list(getattr(trigger, "changed_files", None) or [])
    if src and scm_type in ("git", "svn") and changed_files:
        from workflow.delta_update import _run_unified_diff
        merged: Dict[str, Dict[str, str]] = {}
        for fp in changed_files[:60]:
            # 파일 단위 try/except — 개별 파일 timeout/권한 오류가 앞서 성공한 파일 원문을
            # 폐기하지 않게 한다(sibling classify_changed_functions와 동일 패턴).
            try:
                dt = _run_unified_diff(src, base_ref=getattr(trigger, "base_ref", ""), scm_type=scm_type, file_path=fp)
                for fn, sig in extract_signature_changes(dt or "").items():
                    merged.setdefault(fn, {}).update(sig)
            except Exception as exc:  # noqa: BLE001 — 파일 단위 실패는 건너뛴다
                logger.debug("sig diff failed for %s: %s", fp, exc)
                continue
        return merged
    return {}


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


def _impacted_union(groups: Dict[str, List[str]]) -> Set[str]:
    return set(groups.get("direct", [])) | set(groups.get("indirect_1hop", [])) | set(groups.get("indirect_2hop", []))


def _summarize_actions(
    targets: List[str],
    changed_types: Dict[str, str],
    changed_files: List[str],
    impact_groups: Dict[str, List[str]],
    *,
    auto_generate: bool = False,
    sits_impact_groups: Dict[str, List[str]] | None = None,
) -> Dict[str, Dict[str, Any]]:
    actions: Dict[str, Dict[str, Any]] = {}
    for target in targets:
        # SITS는 cross-module 영향 집합을 사용(과소추정 방지). 나머지는 module-scoped.
        groups = sits_impact_groups if (target == "sits" and sits_impact_groups is not None) else impact_groups
        impacted_all = _impacted_union(groups)
        changed_direct = set(groups.get("direct", []))
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
            # SITS는 통합 영향이라 검토 대상이 cross-module 영향 전체(직접+간접). 나머지는 직접 변경 함수.
            funcs = sorted(impacted_all or changed_direct) if target == "sits" else sorted(changed_direct or impacted_all)
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


def _is_cloudium_mode() -> bool:
    """현재 file_mode가 cloudium(원격/읽기전용 worker)인지. backend 미가용이면 False."""
    try:
        from backend.services.file_resolver import get_resolver
        return getattr(get_resolver(), "mode", "local") != "local"
    except Exception:
        return False


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
        cloudium = _is_cloudium_mode()
        _meta = trigger.metadata or {}
        # Jenkins changeSet 또는 svn revision-range(baseline↔build)의 파일별 editType —
        # 로컬 working-copy diff가 불가하거나(빌드 revision≠로컬) 부정확할 때 변경유형
        # 분류의 1차 근거.
        edit_types = _meta.get("changed_file_edit_types") or {}
        _changed_files_source = _meta.get("changed_files_source") or ""
        _is_changeset = _changed_files_source == "jenkins_changeset"
        # svn_revision_range도 원격 권위 diff(A:B) — editType이 있으면 로컬 diff 대신 사용.
        _is_authoritative_remote = _changed_files_source in ("jenkins_changeset", "svn_revision_range")
        if callable(on_progress):
            on_progress("classify", "변경 함수를 분류 중입니다.", {"changed_files": len(trigger.changed_files or [])})
        # 분류 정밀도(프론트 라벨 정직화용). "file"=파일단위 보수(변경파일 내 전 함수 과대추정),
        # "line"=라인 diff 기반 함수단위. A(정밀화)가 성공하면 아래에서 "line"으로 승격한다.
        _classification_granularity = "file"
        if cloudium or (_is_authoritative_remote and edit_types):
            # cloudium 또는 Jenkins changeSet 연동: git/svn diff subprocess는 원격 source_root
            # (로컬 미존재) 또는 빌드 revision 불일치로 무의미/오정렬. editType이 있으면 그걸로
            # NEW/DELETE까지 정밀 분류, 없으면 확장자 기반(BODY/HEADER) 보수 분류로 직행한다.
            if edit_types:
                changed_types = classify_changed_functions(
                    trigger.source_root, trigger.changed_files, edit_types=edit_types
                )
            else:
                changed_types = _fallback_changed_types_from_files(trigger.changed_files)
        else:
            # 로컬 working-copy diff — 라인 hunk 기반 함수단위 분류(SIGNATURE/NEW/DELETE 판별).
            changed_types = classify_changed_functions(
                trigger.source_root,
                trigger.changed_files,
                scm_type=trigger.scm_type,
                base_ref=trigger.base_ref,
            )
            if changed_types:
                _classification_granularity = "line"
            elif trigger.changed_files:
                changed_types = _fallback_changed_types_from_files(trigger.changed_files)

        _asil_uds_enriched = 0  # UDS 문서에서 ASIL을 보강한 함수 수(소스 주석 미기재분 — 아래서 채움)
        if entry and entry.source_root:
            if callable(on_progress):
                on_progress("impact_analysis", "영향 범위를 계산 중입니다.", {"changed_functions": len(changed_types)})
            sections = _load_source_sections(entry.source_root)
            by_name_raw = sections.get("function_details_by_name", {}) or {}
            by_name = {str(k).strip().lower(): v for k, v in by_name_raw.items() if isinstance(v, dict)}
            # C 소스에 @asil 주석이 없어도 링크된 UDS(함수별 ASIL)로 보강한다 — cloudium U:\는 워커 경유.
            # (소스 ASIL이 있는 함수는 유지, 빈 함수만 채움 → _asil_of·에스컬레이션·커버리지 타깃에 반영)
            _asil_uds_enriched, _asil_still_missing = _enrich_asil_from_uds(
                by_name, getattr(getattr(entry, "linked_docs", None), "uds", "") or "",
            )
            changed_types = _resolve_changed_types_to_functions(
                changed_types, trigger.changed_files, by_name, edit_types=edit_types
            )
            call_map = sections.get("call_map", {}) or {}
            neighbors = _build_neighbors(
                call_map,
                by_name,
                same_module_only=options.same_module_only,
            )
            # SITS는 cross-module 통합 시험 — module 가지치기를 끈 별도 neighbor로 계산해
            # 과소추정을 방지한다(uds/suts는 module-scoped 유지). 가지치기가 꺼져 있으면 동일하므로 생략.
            neighbors_cross = (
                _build_neighbors(call_map, by_name, same_module_only=False)
                if ("sits" in targets and options.same_module_only)
                else None
            )
        else:
            by_name = {}
            neighbors = {}
            neighbors_cross = None

        impact_groups = _hop_limited_impact(
            set(changed_types),
            neighbors,
            max_hop=options.max_hop,
            max_impacted_functions=options.max_impacted_functions,
        )
        sits_impact_groups: Dict[str, List[str]] | None = None
        if neighbors_cross is not None:
            sits_impact_groups = _hop_limited_impact(
                set(changed_types),
                neighbors_cross,
                max_hop=options.max_hop,
                max_impacted_functions=options.max_impacted_functions,
            )
        impacted_total = len(_impacted_union(impact_groups))
        warnings: List[str] = []
        if _asil_uds_enriched:
            warnings.append(
                f"ASIL 보강: 소스 주석에 ASIL이 없는 함수 {_asil_uds_enriched}개를 UDS 문서에서 해석(cloudium 워커 경유)"
            )
        # AUTO를 검토(FLAG)로 강등할 '실질적' 사유만 모은다 — 정보성 경고(Jenkins revision/SITS
        # cross 안내 등)는 AUTO를 봉쇄하지 않는다(과보수 회귀 방지). 한도 초과·ASIL 에스컬레이션만.
        promote_to_review = False
        if impacted_total > options.max_impacted_functions:
            promote_to_review = True
            warnings.append(
                f"impacted function count exceeded limit ({impacted_total}>{options.max_impacted_functions}); promote to review"
            )
        if sits_impact_groups is not None:
            sits_total = len(_impacted_union(sits_impact_groups))
            if sits_total > impacted_total:
                warnings.append(
                    f"SITS cross-module impact ({sits_total}) exceeds same-module impact ({impacted_total}); SITS uses cross-module set"
                )
            if sits_total > options.max_impacted_functions:
                promote_to_review = True
                warnings.append(
                    f"SITS cross-module impacted ({sits_total}) exceeded limit ({options.max_impacted_functions}); promote to review"
                )
        # Jenkins changeSet로 파일집합을 받은 경우의 변경 '유형' 분류 출처를 투명하게 알린다.
        # editType이 있으면 빌드 changeSet 기준, 없으면 로컬 working-copy diff 기준.
        # 정직 고지(X7): diff가 없어 SIGNATURE를 BODY로 분류 → ACTION_MATRIX상 BODY는 sds='-'
        # 이므로, .c만 바뀐 인터페이스(시그니처) 변경은 SDS 검토가 자동 FLAG되지 않을 수 있다
        # (.h가 changeSet에 함께 오면 sds/sts FLAG 가드로 커버됨). ASIL 관련 인터페이스는 수동 확인.
        if _is_authoritative_remote and edit_types:
            _src_label = (
                "SVN revision diff (svn diff --summarize -r baseline:build)"
                if _changed_files_source == "svn_revision_range"
                else "Jenkins changeSet editType"
            )
            warnings.append(
                f"change-type classification from {_src_label} (add→NEW/delete→DELETE/edit→BODY|HEADER); "
                "signature changes not distinguished without line diff — SDS may not be auto-flagged for "
                ".c-only interface changes (verify ASIL-relevant interfaces manually)"
            )
        elif _is_changeset and not edit_types:
            warnings.append(
                "changed file set from Jenkins build changeSet; change-type classification uses local working-copy diff — verify build/local revision alignment"
            )
        # 신규 추가(add) 파일은 baseline A(로컬 작업본) 소스 인덱스(by_name)에 없어 함수 해석이
        # 불가 → 신규 함수의 영향/시험 생성 가이드가 과소보고될 수 있다(svn A:B는 changeSet보다
        # add 노출 빈도↑). by_name 파일경로 매칭(_resolve와 동일: full-path 또는 basename endswith)이
        # 전무한 add 파일이 있으면 명시 고지(빈 결과를 '영향 없음'으로 오인 방지, X7 안전측).
        if edit_types and by_name:
            _bn_files = [
                str((v or {}).get("file") or "").replace("\\", "/").lower()
                for v in by_name.values()
            ]
            _bn_files = [p for p in _bn_files if p]

            def _bn_has(_fp: str) -> bool:
                _fpl = str(_fp).replace("\\", "/").lower()
                _name = _fpl.rsplit("/", 1)[-1]
                return any(p.endswith(_fpl) or p.endswith(_name) for p in _bn_files)

            _unresolved_add = [
                f for f, et in edit_types.items()
                if str(et).strip().lower() == "add" and not _bn_has(f)
            ]
            if _unresolved_add:
                warnings.append(
                    f"{len(_unresolved_add)} newly-added file(s) absent from baseline source index "
                    "(analyzed against baseline revision A) — new functions may be under-reported; review manually"
                )
        # cloudium에서 소스 인덱스(by_name)가 비었는데 변경파일이 있으면 worker read 실패 가능성 →
        # 영향이 과소보고될 수 있음을 명시(빈 결과를 '영향 없음'으로 오인 방지, X7/X9 안전측).
        if cloudium and not by_name and trigger.changed_files:
            warnings.append(
                "cloudium: source index empty (worker read may have failed) — impact may be under-reported; review manually"
            )
        # cloudium(원격/읽기전용)에서는 AUTO 재생성의 입력 read 표면이 아직 미지원(분석/FLAG만 지원)
        # → AUTO를 FLAG로 강등하여 안전하게 검토 아티팩트만 생성한다. (cloudium은 상단에서 계산)
        if cloudium and bool(trigger.auto_generate):
            warnings.append(
                "cloudium mode: AUTO regeneration disabled (read surface not yet supported); downgraded to FLAG"
            )

        # ── 함수별 변경 상세(시그니처 이전→이후 원문) + BODY→SIGNATURE 격상 ──
        # svn A:B editType 경로는 .c edit를 BODY로 고정 분류하나, unified diff에서 실제 시그니처
        # (매개변수/리턴) 변경 원문을 추출할 수 있다. 그 증거가 있으면 (1) UI '변경 상세'에
        # 이전→이후를 렌더하고, (2) 변경유형을 SIGNATURE로 격상해 ACTION_MATRIX상 SDS 자동 FLAG가
        # 걸리게 한다. 영향 집합은 함수 '키'만 쓰므로 격상은 영향범위 무변, 방향은 단방향 안전측
        # (SDS 검토 추가). change_details 키는 소문자(프론트 조인 규약: fn.toLowerCase()).
        change_details: Dict[str, Dict[str, str]] = {}
        if changed_types:
            _ct_by_lower = {str(k).strip().lower(): k for k in changed_types}
            try:
                _sig_map = _collect_signature_changes(trigger, _meta, entry)
            except Exception as _sig_exc:  # noqa: BLE001 — 원문 보강 실패는 분석을 막지 않음
                logger.debug("change_details extraction failed: %s", _sig_exc)
                _sig_map = {}
            for _fn, _sig in (_sig_map or {}).items():
                _actual = _ct_by_lower.get(str(_fn).strip().lower())
                if _actual is None:
                    continue  # 변경유형에 안 잡힌 함수는 잡음 — 제외
                _before = str(_sig.get("before") or "").strip()
                _after = str(_sig.get("after") or "").strip()
                _rec = {}
                if _before:
                    _rec["before"] = _before
                if _after:
                    _rec["after"] = _after
                if _rec:
                    change_details[str(_actual).strip().lower()] = _rec
                # 이전≠이후(둘 다 존재)면 BODY/VARIABLE을 SIGNATURE로 격상(NEW/DELETE/HEADER 보존).
                if _before and _after and _before != _after and changed_types.get(_actual) in ("BODY", "VARIABLE"):
                    changed_types[_actual] = "SIGNATURE"

        # ── ISO 26262 증거 보강: 함수별 ASIL/메타 + ASIL 차등 + 회귀시험 선정 + 커버리지 타깃 ──
        def _asil_of(_fn: str) -> str:
            _a = str((by_name.get(_fn) or {}).get("asil") or "").strip().upper()
            return re.sub(r"^ASIL[\s_-]*", "", _a).strip()  # 'ASIL B'/'ASIL-B' → 'B'

        _changed_set = set(changed_types)
        _impacted_all = _impacted_union(impact_groups) | (
            _impacted_union(sits_impact_groups) if sits_impact_groups else set()
        )
        # 함수별 메타(ASIL/모듈/파일/변경유형) — UI·감사기록·ai-guide ASIL 흐름의 단일 소스.
        function_meta = {
            fn: {
                "asil": _asil_of(fn),
                # 표시용 원본 케이스명(by_name 키는 소문자화됨 → UI 가독성). 미존재 시 fn 폴백.
                "display_name": str((by_name.get(fn) or {}).get("name") or fn),
                "module": str((by_name.get(fn) or {}).get("module_name") or ""),
                "file": str((by_name.get(fn) or {}).get("file") or ""),
                "change_type": changed_types.get(fn, ""),
            }
            for fn in sorted(_changed_set | _impacted_all)
        }
        # ASIL 차등: 직접 변경 함수의 최대 ASIL → 검증강도. B+ = 에스컬레이션, C/D = MC/DC(분기) 재검증 필수.
        _changed_asils = [_asil_of(fn) for fn in _changed_set]
        _max_changed_asil = max(
            (a for a in _changed_asils if a in _ASIL_RANK), key=lambda a: _ASIL_RANK[a], default="",
        )
        asil_escalation = any(_ASIL_RANK.get(a, 0) >= 2 for a in _changed_asils)
        mcdc_required = any(_ASIL_RANK.get(a, 0) >= 3 for a in _changed_asils)
        asil_unknown_changed = sum(1 for a in _changed_asils if a not in _ASIL_RANK)
        coverage_target = _COVERAGE_TARGET.get(_max_changed_asil, "미상(ASIL 확인 필요)")
        if asil_escalation:
            promote_to_review = True  # 안전(ASIL B+) 문서를 사람 검토 없이 자동 재생성하지 않는다
            _mcdc_note = ", MC/DC 재검증 필수" if mcdc_required else ""
            warnings.append(
                f"ASIL escalation: 직접 변경에 ASIL {_max_changed_asil} 함수 포함 — 검증강도 상향"
                f"(커버리지 타깃: {coverage_target}{_mcdc_note})"
            )
        if asil_unknown_changed:
            warnings.append(
                f"직접 변경 함수 중 ASIL 미상 {asil_unknown_changed}개 — 안전 등급 수동 확인 필요(QM 단정 금지)"
            )
        # 회귀시험 선정: 영향 함수 → 기존 SUTS TC / SITS call-chain 집계(재실행 대상 증거).
        _lk = entry.linked_docs if entry else None
        _flagged = sorted(_impacted_all | _changed_set)
        regression_test_set: Dict[str, Any] = {"suts": {}, "sits": {}}
        try:
            if _lk and getattr(_lk, "suts", ""):
                regression_test_set["suts"] = _load_suts_fn_tcs(_lk.suts, _flagged)
            if _lk and getattr(_lk, "sits", ""):
                regression_test_set["sits"] = _load_sits_fn_chains(_lk.sits, _flagged)
        except Exception:  # noqa: BLE001 — 회귀집합은 best-effort, 없어도 분석은 진행
            pass
        regression_test_set["summary"] = {
            "suts_tc_count": sum(len(v) for v in regression_test_set["suts"].values()),
            "sits_chain_count": sum(len(v) for v in regression_test_set["sits"].values()),
            "impacted_function_count": len(_flagged),
            "coverage_target": coverage_target,
            "mcdc_required": mcdc_required,
        }
        # MC/DC delta: 영향 함수의 VectorCAST 커버리지(statement/branch/MC/DC) → ASIL 타깃 대비 gap
        # + 직전 스냅샷 대비 delta(회귀). vectorcast 미연결/RAG metrics 없음 → available=False(분석 계속).
        coverage_gap: Dict[str, Any] = {"available": False}
        _vc_paths = list(getattr(_lk, "vectorcast", []) or []) if _lk else []
        if _vc_paths and _flagged:
            try:
                from workflow.coverage_gap import compute_coverage_gap
                coverage_gap = compute_coverage_gap(
                    _flagged, {fn: _asil_of(fn) for fn in _flagged}, _vc_paths,
                    cache_root=str(REPO_ROOT / ".devops_pro_cache"),
                    scm_id=str(trigger.scm_id or ""),
                    update_baseline=not trigger.dry_run,
                )
            except Exception:  # noqa: BLE001 — 커버리지 연동 실패는 영향도 분석을 막지 않는다
                coverage_gap = {"available": False, "reason": "coverage gap 계산 실패"}
        _cd_impacted = [fn for fn in _flagged if _asil_of(fn) in ("C", "D")]
        if coverage_gap.get("available"):
            _summ = coverage_gap.get("summary", {})
            # '목표 미달(실패)'은 실제 측정값이 타깃에 못 미친 경우만 — 미측정(rate=None,
            # unmeasured_target)은 증거 부재이므로 별도 '미측정' 버킷으로 센다(false 미달 경보 방지).
            _below_safety = [
                r for r in coverage_gap.get("functions", [])
                if not r.get("meets_target") and not r.get("unmeasured_target")
                and r.get("asil") in ("C", "D") and not r.get("asil_unknown")
            ]
            _unmatched_safety = _summ.get("unmatched_safety", 0)
            _unmeasured_safety = _summ.get("unmeasured_safety", 0)
            _missing_safety = _unmatched_safety + _unmeasured_safety  # 미매칭 + 매칭됐으나 메트릭 미측정
            if _below_safety or _missing_safety:
                promote_to_review = True  # ASIL C/D 커버리지 미달/미측정 → 사람 재검증(증거 부재≠충족)
                warnings.append(
                    f"커버리지: ASIL C/D 영향 함수 — 목표 미달 {len(_below_safety)}개 / 미측정 {_missing_safety}개 — 재검증 필요"
                )
            _regr = _summ.get("regressed", 0)
            if _regr:
                warnings.append(f"커버리지 회귀: 직전 대비 {_regr}개 함수 커버리지 하락")
        elif _vc_paths and _cd_impacted:
            # vectorcast는 연결됐으나 커버리지 데이터를 못 읽음 + ASIL C/D 영향 →
            # '증거 없음'을 안전 통과로 보지 않는다(안전측, 수동 확인 유도).
            promote_to_review = True
            warnings.append(
                f"커버리지 데이터 없음(RAG metrics 미생성) — ASIL C/D 영향 함수 {len(_cd_impacted)}개 MC/DC·분기 미검증(수동 확인 필요)"
            )

        actions = _summarize_actions(
            targets,
            changed_types,
            trigger.changed_files,
            impact_groups,
            auto_generate=bool(trigger.auto_generate) and not cloudium,
            sits_impact_groups=sits_impact_groups,
        )
        if promote_to_review:
            for target, info in actions.items():
                if info.get("mode") == "AUTO":
                    info["mode"] = "FLAG"
                    info["status"] = "review_required"

        # ASIL 차등 게이트: ASIL B+ 직접 변경이면 설계/요구사항 시험(sds/sts)도 검토 강제
        # (skipped로 빠지지 않게). C/D는 MC/DC 재검증 플래그를 시험 산출물에 부착.
        _direct = sorted(set(impact_groups.get("direct", [])))
        if asil_escalation:
            for _t in ("sds", "sts"):
                if _t in actions and actions[_t].get("mode") in ("-", None):
                    actions[_t] = {
                        "mode": "FLAG", "status": "review_required",
                        "function_count": len(_direct), "functions": _direct,
                    }
        for _t, _info in actions.items():
            if asil_escalation:
                _info["asil_escalation"] = True
            if mcdc_required and _t in ("suts", "sits", "sts"):
                _info["mcdc_required"] = True
                _info["coverage_target"] = coverage_target

        result = {
            "ok": True,
            "dry_run": bool(trigger.dry_run),
            "trigger": trigger.to_dict(),
            "changed_function_types": dict(sorted(changed_types.items())),
            "change_details": change_details,
            "impact": impact_groups,
            "warnings": warnings,
            "actions": actions,
            "function_meta": function_meta,
            "regression_test_set": regression_test_set,
            "asil": {
                "max_changed": _max_changed_asil,
                "escalation": asil_escalation,
                "mcdc_required": mcdc_required,
                "coverage_target": coverage_target,
                "unknown_changed_count": asil_unknown_changed,
            },
            "coverage_gap": coverage_gap,
            # 분류 정밀도 — 프론트 "변경 함수" 라벨 정직화용. "file"이면 파일단위 보수 분류라
            # 변경 함수 수가 "변경 파일 내 전체 함수"의 과대추정(실제 수정 함수는 더 적음)임을 알린다.
            "classification": {
                "granularity": _classification_granularity,
                "source": _changed_files_source,
                "signature_distinguished": _classification_granularity == "line",
            },
        }
        if "sits" in targets:
            # SITS 전용 cross-module 영향을 항상 노출(계약 일관성). same_module_only가 이미
            # False면 module-scoped == cross이므로 impact_groups를 그대로 사용한다.
            result["impact_sits_cross"] = sits_impact_groups if sits_impact_groups is not None else impact_groups
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
            # FLAG 검토 아티팩트 + AI 가이드가 매 FLAG 타깃마다 동일 인자(changed_types.keys() +
            # linked_docs)로 재파싱하던 문서 로드를 루프 밖에서 1회만(대형 SUTS xlsm 등 최대 ~7회→1회).
            # FLAG 타깃이 하나도 없으면 로드 자체를 생략(종전과 동일한 no-load 동작 보존).
            _has_flag = any(i.get("mode") == "FLAG" for _, i in action_items)
            _flag_fns = list(changed_types.keys())
            _uds_linked = getattr(linked_docs, "uds", "")
            _suts_linked = getattr(linked_docs, "suts", "")
            _sits_linked = getattr(linked_docs, "sits", "")
            _shared_uds_details = _load_uds_fn_details(_uds_linked, _flag_fns) if (_has_flag and _uds_linked) else {}
            _shared_suts_tcs = _load_suts_fn_tcs(_suts_linked, _flag_fns) if (_has_flag and _suts_linked) else {}
            _shared_sits_chains = _load_sits_fn_chains(_sits_linked, _flag_fns) if (_has_flag and _sits_linked) else {}
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
                    # SITS FLAG 아티팩트/가이드는 cross-module 영향 집합을 사용.
                    _groups_for_target = (
                        sits_impact_groups if (target == "sits" and sits_impact_groups is not None) else impact_groups
                    )
                    # Generate AI guide for FLAG targets (best-effort)
                    _ai_guide = None
                    try:
                        from workflow.impact_ai_guide import (
                            generate_impact_guide, ImpactGuideContext,
                        )
                        # 루프 밖에서 1회 로드한 공용 문서 데이터 재사용(재파싱 제거).
                        _ctx = ImpactGuideContext(
                            changed_types=changed_types,
                            impact_groups=_groups_for_target,
                            by_name=by_name or {},
                            uds_fn_details=_shared_uds_details,
                            suts_tcs=_shared_suts_tcs,
                            sits_chains=_shared_sits_chains,
                        )
                        _ai_guide = generate_impact_guide(_ctx)
                    except Exception as _e:
                        logger.debug("AI guide skipped: %s", _e)

                    # 검토 아티팩트 생성도 best-effort — linked_doc 요약이 cloudium U:\\ 접근
                    # 거부 등으로 실패해도 핵심 영향분석 결과(변경파일/시그니처/영향함수)를
                    # 죽이지 않는다(FLAG 액션은 이미 결정됐고 아티팩트는 보조 산출물).
                    try:
                        artifact_path = _write_review_artifact(
                            target,
                            trigger,
                            changed_types,
                            _groups_for_target,
                            by_name,
                            getattr(linked_docs, target, ""),
                            ai_guide=_ai_guide,
                            pre_uds_details=(_shared_uds_details if target == "uds" else None),
                            pre_suts_tcs=(_shared_suts_tcs if target == "suts" else None),
                            pre_sits_chains=(_shared_sits_chains if target == "sits" else None),
                        )
                        info["artifact_path"] = artifact_path
                    except Exception as _art_exc:  # noqa: BLE001
                        logger.debug("review artifact skipped for %s: %s", target, _art_exc)
        if callable(on_progress):
            on_progress("write_audit", "실행 이력을 저장 중입니다.", {"targets": len(actions)})
        audit_payload = {
            "scm_id": trigger.scm_id,
            "trigger": trigger.trigger_type,
            "changed_files": trigger.changed_files,
            "changed_files_source": (trigger.metadata or {}).get("changed_files_source", ""),
            # 어느 revision을 무슨 이유로 분석했는가 — svn revision-range(A:B) 또는 changeSet
            # 폴백 사유. ISO 26262 추적성 증거(로컬 폴백을 '빌드 권위 분석'으로 오인 방지).
            "baseline_revision": (trigger.metadata or {}).get("baseline_revision", ""),
            "build_revision": (trigger.metadata or {}).get("build_revision", ""),
            "linkage_reason": (trigger.metadata or {}).get("linkage_reason", ""),
            "changed_functions": dict(sorted(changed_types.items())),
            "impacted_functions": impact_groups,
            "impacted_functions_sits_cross": sits_impact_groups,
            "targets": targets,
            "dry_run": bool(trigger.dry_run),
            "warnings": warnings,
            "actions": actions,
            "function_meta": function_meta,
            "regression_test_set": regression_test_set,
            "asil": {
                "max_changed": _max_changed_asil,
                "escalation": asil_escalation,
                "mcdc_required": mcdc_required,
                "coverage_target": coverage_target,
                "unknown_changed_count": asil_unknown_changed,
            },
            "coverage_gap": coverage_gap,
            "classification": {
                "granularity": _classification_granularity,
                "source": _changed_files_source,
                "signature_distinguished": _classification_granularity == "line",
            },
        }
        # 감사기록/변경이력은 best-effort — payload가 cloudium U:\\(SMB) 접근 거부 등으로
        # 실패해도 이미 완성된 영향분석 result 반환을 막지 않는다(핵심 결과 보존).
        try:
            audit_path = write_impact_audit(audit_payload)
            result["audit_path"] = str(audit_path)
        except Exception as _audit_exc:  # noqa: BLE001
            logger.warning("impact audit write failed (best-effort): %s", _audit_exc)
            audit_path = None
        try:
            change_log = build_change_log(
                run_id=(audit_path.stem if audit_path else _ts()),
                trigger=trigger.to_dict(),
                result=result,
                previous_linked_docs=previous_linked_docs,
            )
            change_log_path = write_change_log(change_log)
            result["change_log"] = {
                "path": str(change_log_path),
                "run_id": str(change_log.get("run_id") or (audit_path.stem if audit_path else "")),
                "summary": change_log.get("summary") or {},
            }
        except Exception as _cl_exc:  # noqa: BLE001
            logger.warning("impact change-log write failed (best-effort): %s", _cl_exc)
        if callable(on_progress):
            on_progress("done", "완료되었습니다.", {"targets": len(actions)})
        return result
    finally:
        release_run_lock()
