from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List
from workflow.function_module_map import build_function_module_index


REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGE_DIR = REPO_ROOT / "reports" / "impact_changes"

UDS_COMPARE_FIELDS = [
    "description",
    "inputs",
    "outputs",
    "calls_list",
    "globals_global",
    "globals_static",
    "related",
    "asil",
]


def ensure_change_dir() -> Path:
    CHANGE_DIR.mkdir(parents=True, exist_ok=True)
    return CHANGE_DIR


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> Dict[str, Any]:
    # cloudium U:\\(SMB) payload 등 접근 거부 경로는 exists()/read_text가 PermissionError
    # (WinError 5)를 던질 수 있다 — 변경이력(best-effort)이 핵심 분석을 죽이지 않도록 흡수.
    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _artifact_payload_path(path_text: str) -> Path | None:
    raw = str(path_text or "").strip()
    if not raw:
        return None
    path = Path(raw)
    payload_path = path.with_suffix(".payload.json")
    # payload가 cloudium U:\\(SMB) 등 접근 거부 경로면 exists()가 False가 아니라
    # PermissionError(WinError 5)/OSError를 던진다 — 변경 이력(best-effort)이 핵심
    # 영향분석 전체를 죽이지 않도록 예외는 '없음'으로 처리한다.
    try:
        return payload_path if payload_path.exists() else None
    except Exception:
        return None


def _load_payload_with_status(path_text: str) -> tuple[Dict[str, Any], str]:
    """산출물 경로의 `.payload.json` 사이드카를 로드하고 로드 상태를 함께 반환한다.

    상태: "loaded"(정상), "absent"(경로 미지정/부재 — 진짜 없음),
          "unreadable"(경로는 존재하나 권한거부/읽기·파싱 실패 — cloudium U:\\ SMB 등).
    ⚠ M6: unreadable을 absent(빈 dict)로 뭉개면 diff_uds_payload가 모든 함수를 'created'로,
    SUTS/SITS before를 0으로 과대보고한다. 반드시 구분해 unreadable은 diff/delta를 미산출한다.
    """
    raw = str(path_text or "").strip()
    if not raw:
        return {}, "absent"
    payload_path = str(Path(raw).with_suffix(".payload.json"))
    # cloudium(U:\ SMB)은 backend가 직접 못 읽는다 — worker resolver 경유로 읽어 변경이력 delta가
    # cloudium에서도 산출되게 한다. FileNotFoundError=absent(진짜 부재), 접근/파싱 실패=unreadable
    # (존재하나 못 읽음 — '생성'으로 과대보고하지 않도록 구분, M6 정직성 유지).
    try:
        from backend.services.file_resolver import get_resolver
        data = get_resolver().read_bytes(payload_path)
    except FileNotFoundError:
        return {}, "absent"
    except (PermissionError, OSError):
        return {}, "unreadable"
    except Exception:
        # resolver 미가용(테스트/standalone) → 로컬 직접 읽기로 폴백.
        try:
            _p = Path(payload_path)
            if not _p.exists():
                return {}, "absent"
            data = _p.read_bytes()
        except Exception:
            return {}, "unreadable"
    if not data:
        return {}, "unreadable"
    try:
        raw_json = json.loads(data.decode("utf-8", "replace"))
    except Exception:
        return {}, "unreadable"  # 존재하나 파싱 실패
    return (raw_json if isinstance(raw_json, dict) else {}), "loaded"


def _normalize_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_value(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
    if value is None:
        return ""
    return value


def _build_uds_name_map(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = payload.get("function_details") if isinstance(payload.get("function_details"), dict) else {}
    by_name: Dict[str, Dict[str, Any]] = {}
    for info in rows.values():
        if not isinstance(info, dict):
            continue
        name = str(info.get("name") or "").strip().lower()
        if not name:
            continue
        by_name[name] = info
    return by_name


def _summarize_uds_entry(info: Dict[str, Any]) -> Dict[str, Any]:
    calls = info.get("calls_list") if isinstance(info.get("calls_list"), list) else []
    globals_global = info.get("globals_global") if isinstance(info.get("globals_global"), list) else []
    globals_static = info.get("globals_static") if isinstance(info.get("globals_static"), list) else []
    outputs = info.get("outputs") if isinstance(info.get("outputs"), list) else []
    return {
        "calls_count": len(calls),
        "globals_count": len(globals_global) + len(globals_static),
        "output_count": len(outputs),
        "related": str(info.get("related") or "").strip(),
        "asil": str(info.get("asil") or "").strip(),
    }


def diff_uds_payload(before_payload: Dict[str, Any], after_payload: Dict[str, Any], function_names: Iterable[str]) -> Dict[str, Any]:
    before_map = _build_uds_name_map(before_payload)
    after_map = _build_uds_name_map(after_payload)
    changed_functions: List[Dict[str, Any]] = []
    for func_name in sorted({str(name or "").strip().lower() for name in function_names if str(name or "").strip()}):
        before_info = before_map.get(func_name)
        after_info = after_map.get(func_name)
        if not before_info and not after_info:
            continue
        if not before_info and after_info:
            changed_functions.append(
                {
                    "name": str(after_info.get("name") or func_name),
                    "fields_changed": ["created"],
                    "before": {},
                    "after": _summarize_uds_entry(after_info),
                }
            )
            continue
        if before_info and not after_info:
            changed_functions.append(
                {
                    "name": str(before_info.get("name") or func_name),
                    "fields_changed": ["removed"],
                    "before": _summarize_uds_entry(before_info),
                    "after": {},
                }
            )
            continue
        fields_changed = [
            field
            for field in UDS_COMPARE_FIELDS
            if _normalize_value(before_info.get(field)) != _normalize_value(after_info.get(field))
        ]
        if not fields_changed:
            continue
        changed_functions.append(
            {
                "name": str(after_info.get("name") or before_info.get("name") or func_name),
                "fields_changed": fields_changed,
                "before": _summarize_uds_entry(before_info),
                "after": _summarize_uds_entry(after_info),
            }
        )
    return {
        "status": "completed" if changed_functions else "unchanged",
        "summary": {"changed_functions": len(changed_functions)},
        "changed_functions": changed_functions,
    }


def _payload_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_result = payload.get("raw_result") if isinstance(payload.get("raw_result"), dict) else {}
    # ⚠ `summary.primary`가 빈 리스트면 [0]이 IndexError, summary가 list면 .get이 AttributeError →
    #   build_change_log 전체가 예외 → 상위 blanket except가 삼켜 **이 실행의 변경 이력이 통째로
    #   기록되지 않는다**(사용자는 성공으로 보임). 방어적으로 접근한다.
    _summary = payload.get("summary")
    _primary = _summary.get("primary") if isinstance(_summary, dict) else None
    _first = _primary[0] if isinstance(_primary, list) and _primary and isinstance(_primary[0], dict) else {}
    return {
        "test_case_count": payload.get("test_case_count")
        or raw_result.get("test_case_count")
        or _first.get("value", 0),
        "total_sequences": payload.get("total_sequences") or raw_result.get("total_sequences") or 0,
    }


def build_change_log(
    *,
    run_id: str,
    trigger: Dict[str, Any],
    result: Dict[str, Any],
    previous_linked_docs: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    previous_linked_docs = previous_linked_docs or {}
    actions = result.get("actions") if isinstance(result.get("actions"), dict) else {}
    changed_types = result.get("changed_function_types") if isinstance(result.get("changed_function_types"), dict) else {}
    impact = result.get("impact") if isinstance(result.get("impact"), dict) else {}
    docs: Dict[str, Any] = {}

    uds_info = actions.get("uds") if isinstance(actions.get("uds"), dict) else {}
    if uds_info:
        after_payload, _ = _load_payload_with_status(uds_info.get("output_path") or "")
        before_payload, before_status = _load_payload_with_status(previous_linked_docs.get("uds") or "")
        # M6: 이전 payload가 unreadable(권한거부)면 diff를 계산하지 않는다 — 안 그러면 전 함수를
        # 'created'로 과대보고. loaded/absent만 필드 diff를 산출한다(absent는 초판 문서화).
        if uds_info.get("status") == "completed" and after_payload and before_status != "unreadable":
            docs["uds"] = diff_uds_payload(before_payload, after_payload, uds_info.get("functions") or changed_types.keys())
            docs["uds"]["artifact_path"] = str(uds_info.get("output_path") or "")
            if before_status == "absent":
                docs["uds"]["first_generation"] = True  # 이전 UDS 없음 → 증분 아닌 초판(전 함수 신규 문서화)
        else:
            flagged_count = int(uds_info.get("function_count") or 0)
            docs["uds"] = {
                "status": str(uds_info.get("status") or "skipped"),
                "summary": {"changed_functions": flagged_count, "flagged_functions": flagged_count},
                "changed_functions": [{"name": fn, "fields_changed": ["flagged"]} for fn in (uds_info.get("functions") or [])],
                "artifact_path": str(uds_info.get("artifact_path") or uds_info.get("output_path") or ""),
            }
            if before_status == "unreadable" and uds_info.get("status") == "completed":
                # 재생성은 됐으나 이전 payload를 못 읽어 필드 diff 미산출 — 정직 고지(created 과대보고 회피).
                docs["uds"]["before_unavailable"] = True
                docs["uds"]["note"] = "이전 UDS payload 읽기 불가(권한거부 등) — 필드 단위 diff 미산출(과대보고 방지)"

    suts_info = actions.get("suts") if isinstance(actions.get("suts"), dict) else {}
    if suts_info:
        after_payload, _ = _load_payload_with_status(suts_info.get("output_path") or "")
        before_payload, _suts_before_status = _load_payload_with_status(previous_linked_docs.get("suts") or "")
        after_summary = _payload_summary(after_payload)
        before_summary = _payload_summary(before_payload)
        _suts_before_ok = _suts_before_status != "unreadable"  # M6: 못 읽으면 before=0 과대보고 회피
        changed_functions = [
            {"function": name, "change_type": "regenerated"}
            for name in (suts_info.get("functions") or [])
        ]
        docs["suts"] = {
            "status": str(suts_info.get("status") or "skipped"),
            "summary": {
                "changed_functions": len(changed_functions),
                "changed_cases": int(after_summary.get("test_case_count") or 0),
                "changed_sequences": int(after_summary.get("total_sequences") or 0),
                # unreadable이면 0이 아니라 None(불명) — "0→N" 과대보고 대신 "불명→N".
                "before_cases": (int(before_summary.get("test_case_count") or 0) if _suts_before_ok else None),
                "before_sequences": (int(before_summary.get("total_sequences") or 0) if _suts_before_ok else None),
            },
            "changed_cases": changed_functions,
            "artifact_path": str(suts_info.get("output_path") or ""),
            "validation_report_path": str((suts_info.get("result") or {}).get("validation_report_path") or ""),
        }
        if not _suts_before_ok:
            docs["suts"]["before_unavailable"] = True

    sits_info = actions.get("sits") if isinstance(actions.get("sits"), dict) else {}
    if sits_info:
        exec_result = sits_info.get("result") or {}
        after_tc = int(exec_result.get("test_case_count") or sits_info.get("test_case_count") or 0)
        after_sub = int(exec_result.get("total_sub_cases") or sits_info.get("total_sub_cases") or 0)
        before_payload, _sits_before_status = _load_payload_with_status(previous_linked_docs.get("sits") or "")
        _sits_before_ok = _sits_before_status != "unreadable"  # M6: 못 읽으면 delta=after-0 과대보고 회피
        before_tc = int(before_payload.get("test_case_count") or 0)
        before_sub = int(before_payload.get("total_sub_cases") or 0)
        flagged_fn_count = int(sits_info.get("function_count") or 0)
        docs["sits"] = {
            "status": str(sits_info.get("status") or "skipped"),
            "summary": {
                "test_case_count": after_tc,
                "total_sub_cases": after_sub,
                # unreadable이면 before/delta를 None(불명) — "delta = after - 0" 과대보고 대신 미산출.
                "before_test_case_count": (before_tc if _sits_before_ok else None),
                "before_total_sub_cases": (before_sub if _sits_before_ok else None),
                "delta_cases": (after_tc - before_tc if _sits_before_ok else None),
                "delta_sub_cases": (after_sub - before_sub if _sits_before_ok else None),
                "flagged_functions": flagged_fn_count,
            },
            "flagged_functions": list(sits_info.get("functions") or []),
            "artifact_path": str(sits_info.get("artifact_path") or sits_info.get("output_path") or ""),
            "validation_report_path": str(exec_result.get("validation_report_path") or ""),
        }
        if not _sits_before_ok:
            docs["sits"]["before_unavailable"] = True

    for target in ("sts", "sds"):
        info = actions.get(target) if isinstance(actions.get(target), dict) else {}
        if not info:
            continue
        docs[target] = {
            "status": str(info.get("status") or "skipped"),
            "summary": {"flagged_functions": int(info.get("function_count") or 0)},
            "flagged_functions": list(info.get("functions") or []),
            "artifact_path": str(info.get("artifact_path") or ""),
        }

    summary = {
        "uds_changed_functions": int(docs.get("uds", {}).get("summary", {}).get("changed_functions", 0)),
        "suts_changed_functions": int(docs.get("suts", {}).get("summary", {}).get("changed_functions", 0)),
        "suts_changed_cases": int(docs.get("suts", {}).get("summary", {}).get("changed_cases", 0)),
        "suts_changed_sequences": int(docs.get("suts", {}).get("summary", {}).get("changed_sequences", 0)),
        "sits_test_cases": int(docs.get("sits", {}).get("summary", {}).get("test_case_count", 0)),
        "sits_sub_cases": int(docs.get("sits", {}).get("summary", {}).get("total_sub_cases", 0)),
        # delta_cases는 before unreadable 시 None → int(None) 크래시 방지(or 0).
        "sits_delta_cases": int(docs.get("sits", {}).get("summary", {}).get("delta_cases", 0) or 0),
        "sits_flagged": int(docs.get("sits", {}).get("summary", {}).get("flagged_functions", 0)),
        "sts_flagged": int(docs.get("sts", {}).get("summary", {}).get("flagged_functions", 0)),
        "sds_flagged": int(docs.get("sds", {}).get("summary", {}).get("flagged_functions", 0)),
        # M6: 어느 문서든 이전 payload를 못 읽어 diff/delta 미산출이면 상위에 고지(과대보고 아님).
        "before_payload_unavailable": any(
            isinstance(d, dict) and d.get("before_unavailable") for d in docs.values()
        ),
    }

    # 빌드 주소화 + 안전 롤업 필드(additive) — durable 타임라인(build_timeline)이 잡 pruning
    # 이후에도 빌드별로 정렬·집계할 수 있도록 change-log 레코드에 직접 저장한다. 기존 소비처
    # (list_function_history/scm_change_history/ImpactDocRow)는 named key만 읽어 무영향.
    metadata = trigger.get("metadata") if isinstance(trigger.get("metadata"), dict) else {}
    asil_info = result.get("asil") if isinstance(result.get("asil"), dict) else {}
    function_meta = result.get("function_meta") if isinstance(result.get("function_meta"), dict) else {}
    cov_gap = result.get("coverage_gap") if isinstance(result.get("coverage_gap"), dict) else {}
    cov_gap_summary = cov_gap.get("summary") if isinstance(cov_gap.get("summary"), dict) else {}
    # 변경 함수별 ASIL(변경 함수만, 소규모) — 롤업 ASIL 분포를 distinct-함수 기준으로 정확 산출.
    _changed_lower = {str(k).strip().lower() for k in changed_types.keys()}
    changed_function_asil: Dict[str, str] = {
        str(fn): str(meta.get("asil") or "")
        for fn, meta in function_meta.items()
        if isinstance(meta, dict) and str(fn).strip().lower() in _changed_lower
    }
    # 문서별 재생성(AUTO)/검토(FLAG) 모드 집계.
    _doc_modes: Dict[str, str] = {}
    _auto_docs = 0
    _flag_docs = 0
    for _doc, _info in (actions.items() if isinstance(actions, dict) else []):
        _mode = str((_info if isinstance(_info, dict) else {}).get("mode") or "").upper()
        if _mode:
            _doc_modes[str(_doc)] = _mode
        if _mode == "AUTO":
            _auto_docs += 1
        elif _mode == "FLAG":
            _flag_docs += 1

    return {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "trigger": str(trigger.get("trigger_type") or trigger.get("trigger") or ""),
        "dry_run": bool(result.get("dry_run")),
        "scm_id": str(trigger.get("scm_id") or ""),
        "base_ref": str(trigger.get("base_ref") or ""),
        "changed_files": list(trigger.get("changed_files") or []),
        "changed_functions": dict(sorted(changed_types.items())),
        # --- 빌드 주소화 + 안전 롤업 (additive; durable 타임라인용) ---
        "build_number": metadata.get("build_number"),
        "build_revision": metadata.get("build_revision"),
        "build_revision_is_head": bool(metadata.get("build_revision_is_head")),
        "baseline_revision": metadata.get("baseline_revision"),
        "max_asil": asil_info.get("max_changed"),
        "mcdc_required": bool(asil_info.get("mcdc_required")),
        "asil_unknown_count": int(asil_info.get("unknown_changed_count") or 0),
        "changed_function_asil": changed_function_asil,
        "coverage_gap_summary": {
            # ⚠ ISO 정직성: coverage_gap이 available=False(vcast 미연결/계산 실패)면 summary 자체가
            # 없어 아래가 전부 0이 된다. measured로 '미측정'과 '측정 후 회귀 0'을 구분해야 타임라인이
            # 커버리지 없는 빌드를 '정상'으로 위장하지 않는다(증거부재≠충족).
            "measured": bool(cov_gap.get("available")),
            "regressed": int(cov_gap_summary.get("regressed") or 0),
            "unmatched_safety": int(cov_gap_summary.get("unmatched_safety") or 0),
            "unmeasured_safety": int(cov_gap_summary.get("unmeasured_safety") or 0),
        },
        "actions_rollup": {"auto": _auto_docs, "flag": _flag_docs, "doc_modes": _doc_modes},
        "partial_failure": bool(result.get("partial_failure")),
        "impact_counts": {
            "direct": len(impact.get("direct") or []),
            "indirect_1hop": len(impact.get("indirect_1hop") or []),
            "indirect_2hop": len(impact.get("indirect_2hop") or []),
        },
        "summary": summary,
        "documents": docs,
        "artifacts": {
            "uds": str((docs.get("uds") or {}).get("artifact_path") or ""),
            "suts": str((docs.get("suts") or {}).get("artifact_path") or ""),
            "sits": str((docs.get("sits") or {}).get("artifact_path") or ""),
            "sts_review": str((docs.get("sts") or {}).get("artifact_path") or ""),
            "sds_review": str((docs.get("sds") or {}).get("artifact_path") or ""),
        },
    }


def write_change_log(change_log: Dict[str, Any]) -> Path:
    """변경 이력 durable 기록. 파일명은 run_id에서 파생(load_change_log가 run_id로 역조회).

    run_id는 감사 파일 stem(`impact_{ts}_{scm}`)이라 scm이 포함돼 프로젝트 간 충돌이 없다.
    (감사 파일명에 scm이 없던 시절엔 서로 다른 프로젝트가 같은 초에 끝나면 한쪽 이력이 사라졌다.)
    """
    ensure_change_dir()
    run_id = str(change_log.get("run_id") or "").strip() or datetime.now().strftime("impact_%Y%m%d_%H%M%S")
    ts = run_id.replace("impact_", "", 1)
    out = CHANGE_DIR / f"change_{ts}.json"
    _save_json(out, change_log)
    return out


def list_change_logs(scm_id: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    ensure_change_dir()
    target_scm = str(scm_id or "").strip()
    items: List[Dict[str, Any]] = []
    for path in sorted(CHANGE_DIR.glob("change_*.json"), reverse=True):
        raw = _load_json(path)
        if not raw:
            continue
        if target_scm and str(raw.get("scm_id") or "").strip() != target_scm:
            continue
        summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
        items.append(
            {
                "path": str(path),
                "filename": path.name,
                "run_id": str(raw.get("run_id") or path.stem.replace("change_", "impact_")),
                "timestamp": raw.get("timestamp") or path.stem.replace("change_", ""),
                "trigger": raw.get("trigger") or "",
                "dry_run": bool(raw.get("dry_run")),
                "changed_files": raw.get("changed_files") or [],
                "summary": summary,
            }
        )
        if len(items) >= max(1, int(limit or 20)):
            break
    return items


def _safe_run_id(run_id: str) -> str:
    """HTTP 경로에서 유입되는 run_id를 파일명 조각으로 안전화.

    과거 `CHANGE_DIR / raw_id`는 Windows 절대경로('C:\\...')/백슬래시 traversal로 CHANGE_DIR
    밖 임의 JSON을 읽을 수 있었다. 정상 run_id('impact_YYYYMMDD_HHMMSS')는 alnum/_/- 뿐이라
    무변형. 구분자·상위참조 문자는 모두 제거된다.
    """
    return "".join(
        ch if (ch.isalnum() or ch in {"-", "_"}) else "_" for ch in str(run_id or "").strip()
    ).strip("_")


def load_change_log(run_id: str) -> Dict[str, Any]:
    ensure_change_dir()
    raw_id = _safe_run_id(run_id)
    if not raw_id:
        raise KeyError("run_id required")
    # 확장자 없는 raw 후보(임의 파일 read 표면)는 제거하고 change_*.json 규약만 허용.
    candidates = [
        CHANGE_DIR / f"{raw_id}.json",
        CHANGE_DIR / f"change_{raw_id}.json",
        CHANGE_DIR / f"change_{raw_id.replace('impact_', '', 1)}.json",
    ]
    base = CHANGE_DIR.resolve()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        # 방어적 containment 확인(sanitize로 이미 차단되나 belt-and-suspenders).
        if not resolved.is_relative_to(base):
            continue
        if resolved.exists():
            payload = _load_json(resolved)
            if payload:
                return payload
    raise KeyError(raw_id)


def list_function_history(scm_id: str, function_name: str, limit: int = 20) -> List[Dict[str, Any]]:
    target = str(function_name or "").strip().lower()
    if not target:
        return []
    items: List[Dict[str, Any]] = []
    for item in list_change_logs(scm_id=scm_id, limit=max(1, int(limit or 20)) * 5):
        try:
            detail = load_change_log(item["run_id"])
        except KeyError:
            continue
        changed = detail.get("changed_functions") if isinstance(detail.get("changed_functions"), dict) else {}
        if target not in {str(name).strip().lower() for name in changed.keys()}:
            continue
        docs = detail.get("documents") if isinstance(detail.get("documents"), dict) else {}
        uds_doc = docs.get("uds") if isinstance(docs.get("uds"), dict) else {}
        suts_doc = docs.get("suts") if isinstance(docs.get("suts"), dict) else {}
        uds_entry = next(
            (row for row in (uds_doc.get("changed_functions") or []) if str(row.get("name") or "").strip().lower() == target),
            None,
        )
        items.append(
            {
                "run_id": detail.get("run_id") or item["run_id"],
                "timestamp": detail.get("timestamp") or item["timestamp"],
                "change_type": changed.get(target, ""),
                "uds_fields_changed": list((uds_entry or {}).get("fields_changed") or []),
                "suts_changed_cases": int(suts_doc.get("summary", {}).get("changed_cases", 0)) if isinstance(suts_doc.get("summary"), dict) else 0,
            }
        )
        if len(items) >= max(1, int(limit or 20)):
            break
    return items


def list_module_history(scm_id: str, module_name: str, limit: int = 20) -> List[Dict[str, Any]]:
    target = str(module_name or "").strip().lower()
    if not target:
        return []
    items: List[Dict[str, Any]] = []
    for item in list_change_logs(scm_id=scm_id, limit=max(1, int(limit or 20)) * 5):
        try:
            detail = load_change_log(item["run_id"])
        except KeyError:
            continue
        changed = detail.get("changed_functions") if isinstance(detail.get("changed_functions"), dict) else {}
        changed_files = detail.get("changed_files") if isinstance(detail.get("changed_files"), list) else []
        module_index = build_function_module_index(changed, changed_files=changed_files)
        matched_functions = [
            name
            for name, info in module_index.items()
            if str(info.get("best_module") or "").strip().lower() == target
        ]
        if not matched_functions:
            continue
        items.append(
            {
                "run_id": detail.get("run_id") or item["run_id"],
                "timestamp": detail.get("timestamp") or item["timestamp"],
                "module_name": module_name,
                "matched_functions": matched_functions,
                "matched_count": len(matched_functions),
                "changed_files": changed_files,
            }
        )
        if len(items) >= max(1, int(limit or 20)):
            break
    return items


def _norm_asil_bucket(asil: str) -> str:
    """ASIL 값을 표시/집계용 버킷으로 정규화.

    입력은 'ASIL C' / 'C' / 'QM' / 'TBD' / '-' / '' 등 다양(소스=주석 태그·UDS 문서·placeholder).
    ⚠ ISO 정직성: 미상('', 'TBD', 'UNKNOWN', '-')을 QM으로 단정하지 않는다 → 'unknown' 버킷.
    반환: 'A'|'B'|'C'|'D'|'QM'|'unknown'.
    """
    a = str(asil or "").strip().upper()
    if a.startswith("ASIL"):
        a = a[4:].strip()
    if a.startswith("QM"):
        return "QM"
    head = a[:1]
    return head if head in ("A", "B", "C", "D") else "unknown"


def _asil_rank(asil: str) -> int:
    """ASIL 순위(높을수록 안전 중요). QM/미상=0 → max 병합 시 실제 등급이 이긴다."""
    return {"A": 1, "B": 2, "C": 3, "D": 4}.get(_norm_asil_bucket(asil), 0)


def build_timeline(scm_id: str, limit: int = 50) -> Dict[str, Any]:
    """분석된 빌드별 변경 영향 타임라인 + 프로젝트 누적 롤업(durable change-log 기반).

    "분석된 빌드만" — change-log는 영향도 분석이 실제 실행된 빌드만 담는 durable 이력이라
    (reports/impact_changes/, 잡 pruning 무관) 타임라인의 1차 소스로 적합하다. Jenkins
    list_builds(빌드 결과/소요시간)는 엔드포인트에서 best-effort로 조인한다.

    Returns: {"rows": [...최신순...], "rollup": {...누적...}}.
    ⚠ 구 레코드(빌드 주소화 이전)는 build_number/changed_function_asil이 없어 해당 필드가
      None/빈 맵이지만 타임라인 행 자체는 그대로 생성된다(distinct 함수 union은 changed_functions
      이름으로 보강, ASIL은 'unknown' 처리 — 증거부재≠QM).
    """
    lim = max(1, int(limit or 50))
    rows: List[Dict[str, Any]] = []
    # 롤업 누적기 — 함수는 이름(소문자) 기준 distinct union, 충돌 시 ASIL은 max 유지(안전측).
    fn_asil: Dict[str, str] = {}
    files_union: set[str] = set()
    total_auto = 0
    total_flag = 0
    total_regressed = 0
    revisions: List[int] = []
    mcdc_any = False

    for item in list_change_logs(scm_id=scm_id, limit=lim):
        try:
            rec = load_change_log(item["run_id"])
        except KeyError:
            continue
        if not rec:
            continue
        changed_fns = rec.get("changed_functions") if isinstance(rec.get("changed_functions"), dict) else {}
        changed_files = rec.get("changed_files") if isinstance(rec.get("changed_files"), list) else []
        impact_counts = rec.get("impact_counts") if isinstance(rec.get("impact_counts"), dict) else {}
        actions_rollup = rec.get("actions_rollup") if isinstance(rec.get("actions_rollup"), dict) else {}
        cov_summary = rec.get("coverage_gap_summary") if isinstance(rec.get("coverage_gap_summary"), dict) else {}
        fn_asil_map = rec.get("changed_function_asil") if isinstance(rec.get("changed_function_asil"), dict) else {}
        doc_modes = actions_rollup.get("doc_modes") if isinstance(actions_rollup.get("doc_modes"), dict) else {}

        auto_docs = int(actions_rollup.get("auto") or 0)
        flag_docs = int(actions_rollup.get("flag") or 0)
        regressed = int(cov_summary.get("regressed") or 0)
        mcdc_required = bool(rec.get("mcdc_required"))
        rec_summary = rec.get("summary") if isinstance(rec.get("summary"), dict) else {}

        rows.append(
            {
                "run_id": rec.get("run_id") or item.get("run_id"),
                "timestamp": rec.get("timestamp") or item.get("timestamp"),
                "build_number": rec.get("build_number"),
                "build_revision": rec.get("build_revision"),
                "build_revision_is_head": bool(rec.get("build_revision_is_head")),
                "baseline_revision": rec.get("baseline_revision"),
                "base_ref": rec.get("base_ref") or "",
                "dry_run": bool(rec.get("dry_run")),
                "changed_files_count": len(changed_files),
                "changed_functions_count": len(changed_fns),
                "impact_counts": {
                    "direct": int(impact_counts.get("direct") or 0),
                    "indirect_1hop": int(impact_counts.get("indirect_1hop") or 0),
                    "indirect_2hop": int(impact_counts.get("indirect_2hop") or 0),
                },
                "max_asil": rec.get("max_asil") or "",
                "max_asil_bucket": _norm_asil_bucket(rec.get("max_asil") or ""),
                "mcdc_required": mcdc_required,
                "asil_unknown_count": int(rec.get("asil_unknown_count") or 0),
                "auto_docs": auto_docs,
                "flag_docs": flag_docs,
                "doc_modes": doc_modes,
                "coverage_measured": bool(cov_summary.get("measured")),
                "coverage_regressed": regressed,
                "coverage_unmeasured_safety": int(cov_summary.get("unmeasured_safety") or 0),
                "coverage_unmatched_safety": int(cov_summary.get("unmatched_safety") or 0),
                "partial_failure": bool(rec.get("partial_failure")),
                "before_payload_unavailable": bool(rec_summary.get("before_payload_unavailable")),
            }
        )

        # --- 롤업 누적 ---
        files_union.update(str(f) for f in changed_files)
        for name, asil in fn_asil_map.items():
            key = str(name).strip().lower()
            if not key:
                continue
            if key not in fn_asil or _asil_rank(asil) > _asil_rank(fn_asil[key]):
                fn_asil[key] = str(asil or "")
        # 구 레코드는 changed_function_asil가 비었을 수 있으니 distinct union을 함수 이름으로 보강.
        for name in changed_fns.keys():
            key = str(name).strip().lower()
            if key:
                fn_asil.setdefault(key, "")
        total_auto += auto_docs
        total_flag += flag_docs
        total_regressed += regressed
        mcdc_any = mcdc_any or mcdc_required
        rev = rec.get("build_revision")
        if rev is not None and str(rev).strip().isdigit():
            revisions.append(int(str(rev).strip()))

    asil_distribution = {"D": 0, "C": 0, "B": 0, "A": 0, "QM": 0, "unknown": 0}
    for asil in fn_asil.values():
        asil_distribution[_norm_asil_bucket(asil)] += 1

    rollup = {
        "analyzed_build_count": len(rows),
        "distinct_changed_functions": len(fn_asil),
        "distinct_changed_files": len(files_union),
        "cumulative_auto_docs": total_auto,
        "cumulative_flag_docs": total_flag,
        "cumulative_coverage_regressed": total_regressed,
        "mcdc_required_any": mcdc_any,
        "asil_distribution": asil_distribution,
        "revision_range": {
            "base_ref": rows[0].get("base_ref") if rows else "",
            "min_build_revision": min(revisions) if revisions else None,
            "max_build_revision": max(revisions) if revisions else None,
        },
    }
    return {"rows": rows, "rollup": rollup}
