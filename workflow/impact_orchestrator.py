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
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from backend.schemas import ScmLinkedDocs
from backend.services.scm_registry import get_registry_entry
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
    # ⚠ 기본 False(cross-module) — 모듈 가지치기는 '다른 파일/모듈에서 변경 함수를 호출하는 함수'를
    # 영향 집합에서 제외해 UDS/SUTS/STS/SDS 검토 대상에서 누락시킨다(under-report = ISO 26262에서
    # 위험한 방향). 실측(kjpds02): same-module 1hop=0 vs cross 1hop=67(ASIL A 50개·TBD 10개 포함,
    # eeprom_setbyte 등). 과대보고는 안전측이고 impacted>50이면 어차피 검토 승격되므로 워크플로
    # 변화도 없다. 노이즈를 줄이려면 호출측에서 명시적으로 True를 지정할 것.
    same_module_only: bool = False
    # ⚠ 이 값은 두 역할을 겸했다 — (1) BFS 탐색 상한, (2) 검토 승격 임계. cross-module 기본화로
    # seeds가 수백(kjpds02 627)이 되면서 (1)로는 너무 작아 **seeds만으로 이미 초과 → depth1 직후
    # 중단 → indirect_2hop이 항상 미계산**이었다. 승격 임계(review_promote_threshold)는 그대로 두고,
    # 탐색 상한은 seeds 수에 맞춰 동적으로 넉넉히(_bfs_cap) 잡아 2-hop이 실제로 계산되게 한다.
    max_impacted_functions: int = 50            # 검토 승격 임계(변경 없음)
    review_promote_threshold: int = 50          # 명시적 별칭(승격 판정용)
    # BFS 탐색 절대 상한(폭주 방지). seeds가 이보다 많으면 아래 _bfs_cap이 seeds 기준으로 키운다.
    bfs_hard_cap: int = 5000


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
    # ⚠ 원자적 단일 필드 패치 — 과거엔 락 밖에서 entry를 읽어 전체 linked_docs 블롭을 만든 뒤
    #   통째로 덮어써, 그 사이 다른 필드를 바꾼 동시 변경(admin 편집 등)을 조용히 되돌렸다.
    from backend.services.scm_registry import patch_linked_doc_field
    patch_linked_doc_field(entry_id, field, path_text)


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
            # 문서 매칭용으로 surface 필드 확장(라운드: 실제 문서 내용 표시) — 기존 소비처는
            # description/inputs/outputs/asil/related만 읽으므로 추가 필드는 순수 additive(무회귀).
            _g = list(info.get("globals_global") or []) + list(info.get("globals_static") or [])
            _c = list(info.get("calls_list") or []) + list(info.get("called") or [])
            result[fn] = {
                "description": str(info.get("description") or ""),
                "inputs": info.get("inputs") or [],
                "outputs": info.get("outputs") or [],
                "asil": str(info.get("asil") or ""),
                "related": str(info.get("related") or ""),
                "prototype": str(info.get("prototype") or ""),
                "precondition": str(info.get("precondition") or ""),
                "globals": [str(x)[:60] for x in _g if str(x).strip()],
                "calls": [str(x)[:60] for x in _c if str(x).strip()],
            }
    return result


# 링크된 UDS 문서에서 추출한 {함수명(소문자): ASIL} 맵의 경로 캐시.
# 대형 SwUDS docx(수십MB)를 매 impact 실행마다 워커 IPC로 재-read/재파싱하지 않도록 1회만.
# 키는 문서 경로(파일명에 버전 포함이라 개정 시 경로가 바뀜 → staleness 위험 낮음).
_UDS_NAME_ASIL_CACHE: Dict[str, Dict[str, str]] = {}


def _uds_name_asil_map(uds_path: str, warn_sink: Optional[List[str]] = None) -> Dict[str, str]:
    """링크된 UDS(SwUDS) 문서에서 {함수명(소문자): ASIL} 맵을 추출한다.

    C 소스에 Doxygen `@asil` 주석이 없는 프로젝트(예: NE1AW_PORTING)는 함수 ASIL이 전부
    '미상'이 되는데, 실제 등급은 UDS 문서에 있다. UDS는 cloudium U:\\일 수 있으므로 반드시
    워커(`get_resolver().read_bytes`) 경유로 읽는다(직접 접근 금지). 세로 key-value 표
    (`extract_function_asil_from_kv_tables`, v3.02류 'Name'/'ASIL' 행 라벨)를 lxml로 우선 추출하고
    (87MB docx도 초 단위), 부족하면 heading 파서(`parse_swuds_docx`)·reverse-corpus로 보완한다.
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
        # 경로/파일명이 틀렸거나(미완성 placeholder `260XXX` 등) 파일이 없음 → impact의 유일한 문서
        # ASIL 소스가 통째로 죽는다. 정직 표면화(silent-0 방지). ⚠ 캐시하지 않아 매 실행 경고한다
        # (파일명 오탈자/미완성은 사용자가 고쳐야 하므로 첫 실행 후 조용히 사라지면 안 됨).
        if warn_sink is not None:
            warn_sink.append(
                "ASIL: 연결된 UDS 파일을 찾을 수 없습니다(경로/파일명 확인 — 미완성 placeholder 가능) — "
                "ASIL 보강 불가, 설정에서 UDS 문서를 정상 파일로 재연결하세요."
            )
        return {}
    except (PermissionError, OSError):
        # ⚠ 워커 미기동/네트워크 블립을 read_bytes가 PermissionError/OSError로 던진다
        # (file_resolver _ipc_call/_ensure_gate). 이걸 캐시하면 워커가 나중에 떠도 세션 내내
        # 미보강(ASIL 안전게이트 무력화) → 캐시하지 않고 다음 impact 실행서 재시도한다.
        if warn_sink is not None:
            warn_sink.append("ASIL: UDS 파일 접근 실패(cloudium worker 미기동/권한) — ASIL 보강 불가(다음 실행 재시도)")
        return {}
    except Exception:
        return {}  # 기타 일시 오류도 캐시 안 함
    result: Dict[str, str] = {}
    _parse_failed = False  # 파서 예외 여부 — 결정론적 0(예외 없음)만 캐시하고 transient 실패는 미캐시.
    if docx_bytes:
        # docx는 ZIP 컨테이너인데 매직/구조가 깨졌으면(미완성 파일명 `_260XXX` 등 손상) 파서가 조용히
        # 0을 반환해 'heading-less'로 오진단된다. 손상을 명시 표면화하고(캐시 안 함→다음 실행 재시도)
        # 조기 반환한다 — impact의 유일한 문서 ASIL 소스가 통째로 죽은 것이므로 사용자에게 알려야 한다.
        import io as _io
        import zipfile as _zip
        if not _zip.is_zipfile(_io.BytesIO(docx_bytes)):
            if warn_sink is not None:
                warn_sink.append(
                    "ASIL: 연결된 UDS 파일을 열 수 없습니다(손상/미완성 ZIP) — ASIL 보강 불가, "
                    "설정에서 UDS 문서를 정상 파일로 재연결하세요."
                )
            return {}
        # 0) 세로 key-value 표 추출(lxml, python-docx 미사용 → 87MB docx도 초 단위) — v3.02류.
        #    SwUDS v3.02는 함수마다 'Name'/'ASIL' 행 라벨 세로 표라 컬럼/heading 파서가 0건이었다
        #    (SwUFn heading 3106개 있어도 ASIL이 '행 라벨+인접셀'이라 미검출). 빠르므로 먼저 시도하고,
        #    충분히(≥5) 뽑으면 아래 python-docx 파서(document.xml 87MB → ~400s)를 스킵한다.
        try:
            from backend.services.iso26262_doc_asil_extractor import (
                extract_function_asil_from_kv_tables,
            )
            for _n, _a in (extract_function_asil_from_kv_tables(docx_bytes) or {}).items():
                _nl = str(_n or "").strip().lower()
                if _nl and _a:
                    _ex = result.get(_nl)
                    if _ex is None or _asil_rank(_a) > _asil_rank(_ex):
                        result[_nl] = _a
        except Exception:
            _parse_failed = True
        # 1) heading 기반 SwUDS 파서 — 함수명→ASIL 직접(현대/모비스 포맷). kv가 충분하면 스킵.
        if len(result) < 5:
            try:
                from backend.services.swut_swuds_parser import parse_swuds_docx
                _res = parse_swuds_docx(docx_bytes)
                for _e in (_res.entries or []):
                    _n = str(getattr(_e, "name", "") or "").strip().lower()
                    _a = str(getattr(_e, "asil", "") or "").strip()
                    if _n and _a:
                        # first-wins가 아니라 max 등급 유지 — 같은 함수명이 여러 ASIL로 나오면(충돌 14개
                        # 존재) 낮은 등급 채택이 escalation·커버리지 타깃 게이트를 약화(under-report).
                        # by_name 충돌병합(:1250 max)과 동일 안전측 원칙. absent면 첫 값 보존(TBD 포함).
                        _ex = result.get(_n)
                        if _ex is None or _asil_rank(_a) > _asil_rank(_ex):
                            result[_n] = _a
            except Exception:
                _parse_failed = True  # transient 가능(MemoryError 등) → 아래서 0을 캐시하지 않는다
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
                        # first-wins → max 등급(위 heading 파서와 동일 안전측 병합).
                        _ex = result.get(_nl)
                        if _ex is None or _asil_rank(_a) > _asil_rank(_ex):
                            result[_nl] = _a
            except Exception:
                _parse_failed = True
    # 캐시 정책: 비어있지 않은 결과 + **파싱 예외 없이** 나온 결정론적 0만 캐시한다.
    # ⚠ 파서 예외(_parse_failed)로 인한 0은 transient(파서 회귀·일시적 MemoryError)일 수 있어 캐시하면
    # 프로세스 수명 내내 ASIL 미상 → escalation/MC/DC 게이트 무력화(안전 위장) → 미캐시(다음 실행 재시도).
    # (진짜 부재/권한거부/손상 ZIP은 위 read_bytes·is_zipfile 분기에서 이미 미캐시로 처리됨.)
    if result:
        _UDS_NAME_ASIL_CACHE[uds_path] = result
    elif docx_bytes and not _parse_failed:
        # 유효 zip을 파싱했으나 0건(heading-less/미매칭) — **결정론적**이므로 캐시해 대용량 UDS(예 53MB)를
        # 매 impact 실행마다 재-read·재-parse하지 않는다(경로 교정으로 파일이 실제 열리자 매 실행 53MB
        # 3-패스 파싱이 파이프라인을 타임아웃시켰다). 파서 개선 시 백엔드 재기동으로 캐시 무효화.
        _UDS_NAME_ASIL_CACHE[uds_path] = {}
        logger.warning(
            "impact ASIL: UDS를 읽었으나 함수-ASIL 매핑 0건(heading-less/파서 미매칭) — 캐시(재파싱 회피): %s",
            uds_path,
        )
        if warn_sink is not None:
            warn_sink.append(
                "ASIL: UDS를 읽었으나 함수-ASIL 매핑 0건(heading-less 레이아웃/파서 미매칭) — UDS 형식 확인 필요"
            )
    elif docx_bytes:
        # 파싱 예외로 0 — 미캐시(다음 실행 재시도), 사유 표면화.
        logger.warning("impact ASIL: UDS 파싱 예외로 0건 — 캐시하지 않고 다음 실행 재시도: %s", uds_path)
        if warn_sink is not None:
            warn_sink.append("ASIL: UDS 파싱 중 예외로 매핑 0건(일시적일 수 있음) — 다음 실행 재시도")
    return result


def _asil_rank(value: Any) -> int:
    """'ASIL B'/'B'/'TBD'/'' → 등급 순위(미상/미지는 -1). 충돌 사본 중 최대 등급 선택용."""
    a = re.sub(r"^ASIL[\s_-]*", "", str(value or "").strip().upper()).strip()
    return _ASIL_RANK.get(a, -1)


def _is_blank_asil(value: Any) -> bool:
    """ASIL이 '미상'인지 판정. ⚠ uds_generator는 소스/문서에 ASIL이 없으면 빈 문자열이 아니라
    placeholder 'TBD'를 넣는다(report_gen/uds_generator.py:1126) — 빈 문자열만 검사하면 실제
    미태그 함수(예: NE1AW의 497개)를 전부 놓쳐 보강이 no-op가 된다. helpers/uds._is_blank_value와 동일 집합."""
    return str(value or "").strip().upper() in ("", "TBD", "N/A", "-", "UNKNOWN")


def _enrich_asil_from_uds(by_name: Dict[str, Any], uds_path: str, warn_sink: Optional[List[str]] = None) -> tuple[int, int]:
    """소스 주석에 ASIL이 없는 함수만 링크된 UDS의 함수별 ASIL로 보강한다(안전측: 소스 > UDS).

    소스 주석 ASIL이 있는 함수는 절대 덮지 않는다. 보강된 함수엔 `asil_source="uds"` 표식.
    warn_sink: UDS 손상/미매칭 사유 + 소스↔UDS 등급 불일치를 job warnings로 표면화(silent-0 방지).
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
    name_asil = _uds_name_asil_map(uds_path, warn_sink=warn_sink)
    if not name_asil:
        return 0, len(missing)
    enriched = 0
    for fn in missing:
        _a = name_asil.get(fn)
        if _a:
            by_name[fn]["asil"] = _a
            by_name[fn]["asil_source"] = "uds"
            enriched += 1
    # 소스↔UDS 등급 불일치 표면화(잠재 under-report 방향 가시화): 소스가 비-blank인데 UDS가 더 높은
    # 등급이면, 소스 권위(CLAUDE.md ASIL 탐지 #1 @asil 태그) 정책상 **등급은 바꾸지 않되**(자동 상/하향
    # 금지) 문서↔코드 불일치를 사람이 검토하도록 경고만 남긴다. 상향은 정책 변경이라 reviewer/사용자 결정.
    _conflicts = [
        fn for fn, info in by_name.items()
        if isinstance(info, dict) and not _is_blank_asil(info.get("asil"))
        and name_asil.get(fn) and _asil_rank(name_asil[fn]) > _asil_rank(info.get("asil"))
    ]
    if _conflicts and warn_sink is not None:
        _sample = ", ".join(sorted(_conflicts)[:5])
        warn_sink.append(
            f"ASIL: 소스 등급이 UDS보다 낮은 함수 {len(_conflicts)}건 — 소스 권위 유지(등급 불변), "
            f"문서↔코드 ASIL 불일치 수동 검토 필요: {_sample}"
        )
    return enriched, len(missing) - enriched


_SDS_NAME_ASIL_CACHE: Dict[str, Dict[str, str]] = {}


def _sds_name_asil_map(sds_path: str, warn_sink: Optional[List[str]] = None) -> Dict[str, str]:
    """링크된 SDS(SwDS)에서 {함수/컴포넌트명(소문자): ASIL} 맵 — UDS ASIL 보강의 폴백 소스.

    UDS 하나가 손상/부재여도 안전 등급이 통째로 미상이 되지 않도록, `_extract_sds_partition_map`
    (함수단위 asil·인터페이스 함수는 소속 SwCom ASIL 상속)이 이미 파싱하는 asil을 재사용한다.
    cloudium은 worker bytes 경유(직접 open 금지). 실패/손상/미존재는 빈 맵. 경로 캐시(비었으면 미캐시).
    """
    if not sds_path:
        return {}
    _cached = _SDS_NAME_ASIL_CACHE.get(sds_path)
    if _cached is not None:
        return _cached

    def _warn(msg: str) -> None:
        if warn_sink is not None:
            warn_sink.append(msg)

    try:
        from backend.services.file_resolver import get_resolver
        data = get_resolver().read_bytes(sds_path)
    except FileNotFoundError:
        # FileNotFoundError는 OSError 서브클래스라 별도로 먼저 잡아 사유를 구분 표면화(reviewer W2 — UDS와 대칭).
        _warn("ASIL: SDS 파일을 찾을 수 없습니다(경로/파일명 확인) — SDS ASIL 폴백 불가")
        return {}
    except (PermissionError, OSError):
        _warn("ASIL: SDS 파일 접근 실패(cloudium worker 미기동/권한) — SDS ASIL 폴백 불가")
        return {}
    except Exception:
        return {}
    if not data:
        return {}
    import io as _io
    import os as _os
    import tempfile as _tf
    import zipfile as _zip
    if not _zip.is_zipfile(_io.BytesIO(data)):
        _warn("ASIL: SDS 파일을 열 수 없습니다(손상 ZIP) — SDS ASIL 폴백 불가")
        return {}
    tmp_path = ""
    result: Dict[str, str] = {}
    try:
        from report_gen.requirements import _extract_sds_partition_map, _strip_ret_type_prefix
        with _tf.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(data)
            tmp_path = f.name
        pm = _extract_sds_partition_map(tmp_path) or {}
        for key, info in pm.items():
            info = info or {}
            # ⚠ kind='function' 엔트리만 신뢰(reviewer W3). _extract_sds_partition_map은 SwCom 컴포넌트
            # (짧은 이름 EEPROM/Diag 등)와 그 인터페이스 함수를 **같은 소문자 키 공간**에 넣는다 → 컴포넌트명이
            # 무관한 C 함수명과 우연히 겹치면 잘못된 ASIL이 조용히 주입된다(silent over/under-report). 함수만.
            if info.get("kind") != "function":
                continue
            k = str(key).strip().lower()
            a = str(info.get("asil") or "").strip()
            # _asil_rank>=0: {QM,A,B,C,D}만 채택(reviewer W5) — 'TBD2'/'B(잠정)' 오타값이 게이트(_ASIL_RANK.get
            # ...,0)를 조용히 미발동시키는 under-report를 막는다.
            if k and a and not _is_blank_asil(a) and _asil_rank(a) >= 0:
                # 동명 충돌은 max 등급(안전측, _uds_name_asil_map과 동일 원칙).
                _ex = result.get(k)
                if _ex is None or _asil_rank(a) > _asil_rank(_ex):
                    result[k] = a
        # 반환형 헝가리안 접두사 alias(라운드111 추적성 _alias_safe 미러 — requirements.py:2078-2103):
        # SDS는 'u16g_drvin_motorspeed'처럼 반환형(u8/u16/u32/s8/s16/s32)을 붙여 표기하나 소스 by_name
        # 키는 순수명('g_drvin_motorspeed') → _enrich_asil_from_sds의 정확조회 name_asil.get(fn)가 미스
        # (폴백 커버리지 정체). base가 ① 기존 SDS 키(pm 전체, 컴포넌트 포함)가 아니고 ② 단 하나의 접두사형
        # 에서만 파생될 때만 alias 등록 — u8g_/s8g_(unsigned/signed 반환형 = 별개 함수 가능)이 같은 base로
        # 모이면 서로 다른 함수에 ASIL이 오union되므로 생략(over/under-report 방지, 안전측 보수).
        _all_pm_keys = {str(_rk).strip().lower() for _rk in pm.keys()}
        _pref_base_cnt: Dict[str, int] = {}
        for _kk in _all_pm_keys:
            _bb = _strip_ret_type_prefix(_kk)
            if _bb != _kk:
                _pref_base_cnt[_bb] = _pref_base_cnt.get(_bb, 0) + 1
        for _k in list(result.keys()):
            _b = _strip_ret_type_prefix(_k)
            if _b != _k and _b not in _all_pm_keys and _pref_base_cnt.get(_b, 0) == 1:
                result[_b] = result[_k]  # 순수명 alias에 원 등급 복제(base는 신규 키 — 기존 정확매칭 불변)
    except Exception:
        _warn("ASIL: SDS 파싱 실패 — SDS ASIL 폴백 불가")
        return {}  # 파싱 실패 — 캐시 안 함
    finally:
        if tmp_path:
            try:
                _os.unlink(tmp_path)
            except OSError:
                pass
    if result:
        _SDS_NAME_ASIL_CACHE[sds_path] = result
    else:
        _warn("ASIL: SDS를 읽었으나 함수-ASIL 매핑 0건(kind='function' 미검출/형식) — SDS ASIL 폴백 미적용")
    return result


def _enrich_asil_from_sds(by_name: Dict[str, Any], sds_path: str, warn_sink: Optional[List[str]] = None) -> tuple[int, int]:
    """UDS 보강 후에도 소스가 미상(TBD)인 함수만 SDS ASIL로 폴백 보강한다(소스 > UDS > SDS).

    ⚠ 안전측: TBD인 함수만 채우고 이미 등급이 있는 함수는 절대 덮지 않는다(등급 낮추기 없음).
    보강된 함수엔 `asil_source="sds"` 표식. 반환: (보강한 함수 수, 보강 후 남은 미상 수).
    """
    if not sds_path or not isinstance(by_name, dict):
        return 0, 0
    missing = [
        fn for fn, info in by_name.items()
        if isinstance(info, dict) and _is_blank_asil(info.get("asil"))
    ]
    if not missing:
        return 0, 0
    name_asil = _sds_name_asil_map(sds_path, warn_sink=warn_sink)
    if not name_asil:
        return 0, len(missing)
    enriched = 0
    for fn in missing:
        a = name_asil.get(fn)
        if a:
            by_name[fn]["asil"] = a
            by_name[fn]["asil_source"] = "sds"
            enriched += 1
    return enriched, len(missing) - enriched


_SUDS_FN_SWCOM_CACHE: Dict[str, Dict[str, List[str]]] = {}
_SDS_COM_ASIL_CACHE: Dict[str, Dict[str, str]] = {}


def _suds_fn_swcom_map(uds_path: str) -> Dict[str, List[str]]:
    """SwUDS에서 {함수명(소문자): [SwCom_NN]}(Related ID) — SwCom ASIL 상속 폴백용. 경로 캐시.
    cloudium U:\\는 워커(read_bytes) 경유. 접근/파싱 실패는 빈 맵(비차단·미캐시)."""
    if not uds_path:
        return {}
    _c = _SUDS_FN_SWCOM_CACHE.get(uds_path)
    if _c is not None:
        return _c
    try:
        from backend.services.file_resolver import get_resolver
        data = get_resolver().read_bytes(uds_path)
    except (FileNotFoundError, PermissionError, OSError):
        return {}
    except Exception:
        return {}
    try:
        from backend.services.iso26262_doc_asil_extractor import extract_function_swcom_from_kv_tables
        m = extract_function_swcom_from_kv_tables(data) or {}
    except Exception:
        m = {}
    if m:
        _SUDS_FN_SWCOM_CACHE[uds_path] = m
    return m


def _sds_com_asil_map(sds_path: str) -> Dict[str, str]:
    """SDS에서 {SwCom_NN: ASIL}(컴포넌트 등급, 유효등급만) — SwCom ASIL 상속 폴백용. 경로 캐시.
    ⚠ SwCom_NN 키만 채택(extract_component_asil_from_sds가 이름 별칭·노이즈 키도 반환) — 오귀속 방지."""
    if not sds_path:
        return {}
    _c = _SDS_COM_ASIL_CACHE.get(sds_path)
    if _c is not None:
        return _c
    try:
        from backend.services.file_resolver import get_resolver
        data = get_resolver().read_bytes(sds_path)
    except (FileNotFoundError, PermissionError, OSError):
        return {}
    except Exception:
        return {}
    result: Dict[str, str] = {}
    try:
        from backend.services.iso26262_doc_asil_extractor import extract_component_asil_from_sds
        raw = extract_component_asil_from_sds(data) or {}
        for k, v in raw.items():
            # IGNORECASE + canonical 'SwCom_NN' — SUDS측(extract_function_swcom_from_kv_tables) 정규화와
            # 대칭. 타 프로젝트 SDS가 'SWCOM_13'/'swcom_13'이어도 매칭(과거 대소문자 민감 silent drop, reviewer #2).
            _m = re.fullmatch(r"SwCom_(\d+)", str(k).strip(), re.IGNORECASE)
            if _m and not _is_blank_asil(v) and _asil_rank(v) >= 0:
                _ck = "SwCom_" + _m.group(1)
                # 동일 SwCom이 여러 표에 나오면 max 등급(안전측).
                _ex = result.get(_ck)
                if _ex is None or _asil_rank(v) > _asil_rank(_ex):
                    result[_ck] = str(v).strip()
    except Exception:
        return {}
    if result:
        _SDS_COM_ASIL_CACHE[sds_path] = result
    return result


def _enrich_asil_from_swcom(
    by_name: Dict[str, Any], uds_path: str, sds_path: str, warn_sink: Optional[List[str]] = None,
) -> tuple[int, int]:
    """소스·UDS·SDS 함수 등급으로도 미상인 함수를, SwUDS Related ID의 소속 SwCom → SDS 컴포넌트
    ASIL로 폴백 보강한다(ISO 26262 컴포넌트 ASIL 상속 — 가장 약한 폴백, 우선순위 맨 마지막).

    ⚠ 안전측: TBD/N/A인 함수만 채우고(상향만·등급 낮추기 없음), 여러 SwCom 소속이면 max 등급.
    문서에 명시된 Related ID 기반이라 fuzzy 이름매칭 아님(오귀속 위험 낮음). 보강 함수엔
    asil_source="swcom" 표식 + 경고로 표면화(SwUDS 함수별 ASIL 누락 가시화 — 문서 등급 보완 유도).
    반환: (보강 함수 수, 보강 후 남은 미상 수).
    """
    if not uds_path or not sds_path or not isinstance(by_name, dict):
        return 0, 0
    missing = [
        fn for fn, info in by_name.items()
        if isinstance(info, dict) and _is_blank_asil(info.get("asil"))
    ]
    if not missing:
        return 0, 0
    fn_swcom = _suds_fn_swcom_map(uds_path)
    if not fn_swcom:
        return 0, len(missing)
    com_asil = _sds_com_asil_map(sds_path)
    if not com_asil:
        return 0, len(missing)
    enriched = 0
    for fn in missing:
        _grades = [com_asil[sc] for sc in (fn_swcom.get(fn) or []) if sc in com_asil]
        if not _grades:
            continue
        by_name[fn]["asil"] = max(_grades, key=_asil_rank)  # 다중 SwCom 소속은 max(안전측)
        by_name[fn]["asil_source"] = "swcom"
        enriched += 1
    if enriched and warn_sink is not None:
        warn_sink.append(
            f"ASIL: 함수 등급이 문서에 N/A였으나 소속 SwCom(SDS 컴포넌트) 등급으로 {enriched}건 상속 보강 "
            "— SwUDS 함수별 ASIL 누락 가능(문서 등급 보완 권장)"
        )
    return enriched, len(missing) - enriched


def _load_suts_fn_tcs(
    linked_doc: str, flagged_fns: List[str], warn_sink: Optional[List[str]] = None,
    content_sink: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[str]]:
    """Return {fn_name: [tc_id, ...]} by parsing the existing SUTS xlsm.

    content_sink(선택): 제공되면 {fn: [{tc_id, action, precondition, inputs, expected}]}로
    실제 TC 내용(Test Action·실입력·실기대값)을 채운다 — 문서 카드에 '예측' 대신 실 내용 표시용.
    회귀 집계(return {fn:[tc_id]})는 불변(순수 additive).

    ⚠ cloudium(U:\\)에서는 backend가 파일을 직접 열 수 없다 — 과거 `load_workbook(linked_doc)`
    직접 open은 `_safe_exists`가 PermissionError→False로 걸러 **조용히 0**(회귀 TC 미집계)을
    유발했다. 반드시 worker(`get_resolver().read_bytes`) 경유 bytes로 읽는다.
    실패는 빈 dict로 폴백하되 **사유를 warn_sink에 남겨 silent 0을 방지**한다."""
    if not linked_doc:
        return {}

    def _warn(msg: str) -> None:
        if warn_sink is not None:
            warn_sink.append(msg)

    try:
        from backend.services.file_resolver import get_resolver
        data = get_resolver().read_bytes(linked_doc)
    except FileNotFoundError:
        _warn("회귀 TC: 연동 SUTS 문서를 찾을 수 없어 재실행 TC 집계를 건너뜀")
        return {}
    except (PermissionError, OSError):
        _warn("회귀 TC: SUTS 문서 접근 실패(cloudium worker 미기동/권한) — 재실행 TC 미집계")
        return {}
    except Exception:
        return {}
    if not data:
        return {}
    try:
        from tools.export_suts_vectorcast import build_vectorcast_model, bare_fn_name  # type: ignore
        model = build_vectorcast_model(linked_doc, target_functions=flagged_fns, source_bytes=data)
    except ValueError:
        _warn("회귀 TC: SUTS 문서 형식 미인식(TC 시트 없음) — 재실행 TC 미집계")
        return {}
    except Exception:
        _warn("회귀 TC: SUTS 파싱 실패 — 재실행 TC 미집계")
        return {}
    result: Dict[str, List[str]] = {}
    _unit_exc = 0  # malformed 유닛(예외) 개수 — 격리하고 사유만 표면화(전체 집합 유실 방지)
    _row_drops = 0  # 정상 유닛 내부의 기형 TC 행(dict 아님) — 조용히 걸러지므로 개수만 집계(정직화 완성)
    for unit in model.get("units") or []:
        try:
            if not isinstance(unit, dict):
                _unit_exc += 1
                continue
            # unit_name은 템플릿에 따라 시그니처(HDPDM01 'void g_SysOs_WdiCtrl( void )')일 수 있어
            # bare 식별자로 정규화한다 — 프론트/스코프 필터(_direct_lc)가 SVN diff의 bare 함수명과
            # 조인하므로, 시그니처 그대로면 매칭 실패해 카드가 '미파싱'·회귀 TC 0이 됐다(KJPDS02는 무변경).
            name = bare_fn_name(unit.get("unit_name"))
            # each test_case row carries base_tc_id (the TC block identifier)
            _seqs = unit.get("test_cases") or []
            _row_drops += sum(1 for tc in _seqs if not isinstance(tc, dict))  # 기형 행 집계(정상은 0 — happy-path 무영향)
            tcs = [str(tc.get("base_tc_id") or "") for tc in _seqs if isinstance(tc, dict) and tc.get("base_tc_id")]
            if name and tcs:
                result[name] = list(dict.fromkeys(tcs))
                # 실 TC 내용 보존(문서 카드용) — 함수당 상위 3 시퀀스, action 300자.
                if content_sink is not None:
                    seqs_out = []
                    for tc in _seqs[:3]:
                        if not isinstance(tc, dict):
                            continue
                        action = str(tc.get("description") or "").strip()
                        pre = str(tc.get("precondition") or "").strip()
                        # 실 TC 시트·행 위치(exporter가 test_case["source"]로 부여) 전달 — 문서 카드가
                        # "이 TC(행 N)를 이렇게 수정" 앵커를 표시하게 한다. 비어있으면 생략(행 번호 날조 금지).
                        _src = tc.get("source") or {}
                        _src = _src if isinstance(_src, dict) else {}
                        _loc = {k: _src.get(k) for k in ("sheet", "tc_row", "sequence_row") if _src.get(k) is not None}
                        _seq = {
                            "tc_id": str(tc.get("base_tc_id") or ""),
                            "action": action[:300],
                            "precondition": pre[:200],
                            "inputs": _cap_kv(tc.get("inputs")),
                            "expected": _cap_kv(tc.get("expected")),
                        }
                        if _loc:
                            _seq["loc"] = _loc
                        seqs_out.append(_seq)
                    if seqs_out:
                        content_sink[name] = seqs_out
        except Exception:  # noqa: BLE001 — 한 유닛의 기형 데이터가 전체 회귀집합을 무너뜨리지 않게 격리  # silent-ok(_unit_exc로 집계·표면화)
            _unit_exc += 1
            continue
    if _unit_exc:
        _warn(f"회귀 TC: SUTS 유닛 {_unit_exc}건 파싱 예외로 건너뜀 — 재실행 집합 과소 가능(데이터 형식 확인)")
    if _row_drops:
        _warn(f"회귀 TC: SUTS TC 행 {_row_drops}건 형식 이상으로 건너뜀 — 재실행 집합 과소 가능(데이터 형식 확인)")
    if not result and flagged_fns:
        _warn("회귀 TC: 영향 함수와 SUTS 유닛명이 매칭되지 않아 재실행 TC 0(이름 규칙 확인)")
    # reviewer Finding#5: 파서 경고를 유실하지 않고 표면화. 단 **유닛 누락(회귀집합 과소)** 경고는
    # unit을 실제로 떨어뜨리는 코드(empty_test_case_block/missing_unit_name)만 센다 —
    # empty_expected/verification_required_expected 는 시퀀스별 무해 경고(입력전용 스텝 등)라
    # 이를 '유닛 누락'으로 합산하면 오경보다(전용 파서 컬럼탐지 수정 후 empty_expected가 다수라
    # 994건 '누락 가능' 허위 경보가 났었다). 무해 경고는 별도 사유로만 남긴다.
    _export_warns = model.get("export_warnings") or []
    _drop_codes = {"empty_test_case_block", "missing_unit_name"}
    _unit_drops = sum(1 for w in _export_warns if isinstance(w, dict) and w.get("code") in _drop_codes)
    if _unit_drops:
        _warn(f"회귀 TC: SUTS 유닛 누락 경고 {_unit_drops}건(빈 TC 블록/유닛명 누락) — 재실행 집합 과소 가능")
    return result


# 링크 UDS docx를 worker로 1회 읽어 parse_swuds_docx 내용({name: {description, heading}})을 캐시.
# 대형 docx(수십MB) 재-read/재파싱 회피(_UDS_NAME_ASIL_CACHE와 동일 원칙, 경로 키).
_UDS_CONTENT_CACHE: Dict[str, Dict[str, Dict[str, Any]]] = {}


def _load_uds_fn_content(
    uds_path: str, flagged_fns: List[str], warn_sink: Optional[List[str]] = None
) -> Dict[str, Dict[str, Any]]:
    """함수별 UDS 실 내용({fn(lower): {description, heading, prototype, globals[], calls[]}}).

    사이드카(생성 UDS, 로컬 `<docx>.payload.json`)의 풍부 필드를 우선하고, 없으면(=cloudium 링크
    문서 대다수) 링크 docx를 worker(`get_resolver().read_bytes`)로 읽어 parse_swuds_docx의
    heading+description+prototype(표 'Prototype' 행)으로 보완한다. 문서 카드에 '예측' 대신 실 내용
    표시 + 시그니처 변경 시 원문→변경안 기준선용. 실패는 빈 dict(비차단)이되 사유는 warn_sink로
    표면화('미파싱'이 진짜 미연동인지 접근/파싱 실패인지 구분 — reviewer W3)."""
    if not uds_path:
        return {}

    def _warn(msg: str) -> None:
        if warn_sink is not None:
            warn_sink.append(msg)
    fset = {str(f).strip().lower() for f in flagged_fns}
    out: Dict[str, Dict[str, Any]] = {}
    # 1) 사이드카 — 풍부(description/prototype/globals/calls). cloudium 링크문서엔 대개 없음.
    try:
        for fn, d in (_load_uds_fn_details(uds_path, flagged_fns) or {}).items():
            entry = {
                "description": str(d.get("description") or "").strip()[:300],
                "prototype": str(d.get("prototype") or "").strip()[:200],
                "globals": [str(x) for x in (d.get("globals") or [])][:10],
                "calls": [str(x) for x in (d.get("calls") or [])][:10],
            }
            if entry["description"] or entry["prototype"] or entry["globals"] or entry["calls"]:
                out[str(fn).strip().lower()] = entry
    except Exception:
        pass
    # 2) parse_swuds_docx(worker) — heading+description으로 미충족 함수 보완(경로 캐시).
    _missing = fset - set(out.keys())
    if _missing:
        _entries = _UDS_CONTENT_CACHE.get(uds_path)
        if _entries is None:
            _entries = {}
            try:
                from backend.services.file_resolver import get_resolver
                data = get_resolver().read_bytes(uds_path)
                if data:
                    # 0) lxml 세로 kv 추출 우선(초 단위) — v3.02류 대형 docx를 python-docx
                    # parse_swuds_docx(50MB에 22~41s)로 매번 파싱하던 것을 대체. lxml이 flagged를
                    # 다 채우면 아래 41s 파서를 아예 건너뛴다(속도 + 중단 시 빈 캐시 굳는 위험 완화).
                    try:
                        from backend.services.iso26262_doc_asil_extractor import (
                            extract_function_details_from_kv_tables,
                        )
                        for _n, _d in (extract_function_details_from_kv_tables(data) or {}).items():
                            _desc = str((_d or {}).get("description") or "").strip()
                            _proto = str((_d or {}).get("prototype") or "").strip()
                            if _desc or _proto:
                                _e = {"description": _desc[:300]}
                                if _proto:
                                    _e["prototype"] = _proto[:200]
                                _entries[_n] = _e
                    except Exception:  # silent-ok — lxml 실패는 아래 heading 파서로 폴백(비차단)
                        pass
                    # 1) heading 가로표 파서 — lxml이 flagged를 다 못 채웠을 때만(HDPDM01류 가로표
                    # 문서는 lxml 세로kv가 0건 → 여기서 채운다). heading은 lxml이 안 주므로 보강.
                    if _missing - set(_entries.keys()):
                        from backend.services.swut_swuds_parser import parse_swuds_docx
                        res = parse_swuds_docx(data)
                        for e in (res.entries or []):
                            n = str(getattr(e, "name", "") or "").strip().lower()
                            if not n:
                                continue
                            desc = str(getattr(e, "description", "") or "").strip()
                            head = str(getattr(e, "heading_text", "") or "").strip()
                            # prototype — 링크 UDS도 표에 있으면 실 선언 표시/원문→변경안 기준선.
                            proto = str(getattr(e, "prototype", "") or "").strip()
                            _prev = _entries.get(n)
                            if _prev is not None:
                                # lxml이 이미 desc/proto 채움 → heading만 보강(중복 방지).
                                if head and not _prev.get("heading"):
                                    _prev["heading"] = head[:120]
                                continue
                            if desc or head or proto:
                                _entries[n] = {"description": desc[:300], "heading": head[:120]}
                                if proto:
                                    _entries[n]["prototype"] = proto[:200]
                if not _entries:
                    # 파싱은 됐으나 내용 0 — heading-less 레이아웃 등(예: kjpds02 UDS). 정직 사유.
                    _warn("문서 내용: UDS heading 파서가 내용을 추출하지 못함(heading-less 레이아웃/사이드카 부재) — UDS 카드는 '미파싱' 표기")
            except Exception:
                _entries = {}
                _warn("문서 내용: UDS 접근/파싱 실패(cloudium worker/파서 예외) — UDS 카드 '미파싱'")
            _UDS_CONTENT_CACHE[uds_path] = _entries
        for n in _missing:
            if n in _entries:
                out[n] = _entries[n]
    return out


def _load_sds_fn_desc(
    sds_path: str, flagged_fns: List[str], warn_sink: Optional[List[str]] = None
) -> Dict[str, str]:
    """함수/컴포넌트별 SDS 설명({key(lower): description}). worker bytes→tmp→_extract_sds_partition_map
    (report_gen). 영향 함수명과 매칭되는 항목만 반환. cloudium 직접 open 금지(bytes→tmp). 실패는 빈 dict이되
    사유는 warn_sink로 표면화(reviewer W3 — 정직성)."""
    if not sds_path:
        return {}

    def _warn(msg: str) -> None:
        if warn_sink is not None:
            warn_sink.append(msg)

    try:
        from backend.services.file_resolver import get_resolver
        data = get_resolver().read_bytes(sds_path)
    except Exception:
        _warn("문서 내용: SDS 접근 실패(cloudium worker 미기동/권한) — SDS 카드 '미파싱'")
        return {}
    if not data:
        return {}
    import os
    import tempfile
    tmp_path = ""
    pm: Dict[str, Dict[str, str]] = {}
    try:
        from report_gen.requirements import _extract_sds_partition_map
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(data)
            tmp_path = f.name
        pm = _extract_sds_partition_map(tmp_path) or {}
    except Exception:
        _warn("문서 내용: SDS 파싱 실패 — SDS 카드 '미파싱'")
        pm = {}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    fset = {str(f).strip().lower() for f in flagged_fns}
    # 헝가리안 접두어(반환형? + 저장클래스 [sgl]_)만 닫힌 집합으로 제거 — SDS 인터페이스명(대개
    # prefix 없음)과 flagged 함수명(prefix 有, 예: s_tunningparamread_16bitdata) 불일치를 흡수.
    # ⚠ 도메인 접두어(adc_/spi_/uart_)는 [sgl]_ 조건 불충족이라 벗기지 않는다 — 열린 `[a-z]{1,4}_`
    # 였다면 spi_read→read가 adc_read 설명을 조용히 오귀속했다(X7). report_gen `_LAYER_CORE_PREFIX_RE`
    # 와 동일 원칙의 닫힌 패턴. exact 우선.
    _pref = re.compile(r"^(?:u8|u16|u32|s8|s16|s32)?[sgl]_")

    def _norm(name: str) -> str:
        return _pref.sub("", str(name).strip().lower())

    # 정규화 인덱스는 함수 엔트리만 대상(컴포넌트 오귀속 방지). 정규화 후 서로 다른 원본이 겹치면
    # 모호하므로 충돌로 표시해 제외(잘못된 함수의 설명을 붙이지 않음).
    norm_index: Dict[str, str] = {}
    norm_collision: set = set()
    for key, info in pm.items():
        if (info or {}).get("kind") != "function":
            continue
        lk = str(key).strip().lower()
        nk = _norm(lk)
        if not nk:
            continue
        if nk in norm_index:
            if norm_index[nk] != lk:
                norm_collision.add(nk)
        else:
            norm_index[nk] = lk
    out: Dict[str, str] = {}
    for f in fset:
        info = pm.get(f)  # 1) exact match(컴포넌트/함수 무관 — 기존 동작 유지)
        if info is None:  # 2) 접두어 정규화 대조(함수 엔트리·충돌 없을 때만)
            nf = _norm(f)
            if nf and nf not in norm_collision and nf in norm_index:
                info = pm.get(norm_index[nf])
        if not info:
            continue
        desc = str((info or {}).get("description") or "").strip()
        if not desc:  # 3) 인터페이스 행 desc가 비면 소속 컴포넌트 설명으로 폴백(출처 라벨링)
            comp = str((info or {}).get("component_description") or "").strip()
            if comp:
                desc = f"(컴포넌트 설명) {comp}"
        if desc:
            out[f] = desc[:300]  # 키는 flagged fn — 프론트 docContentFor 조회 키와 일치
    return out


def _cap_kv(d: Any, n: int = 5) -> Dict[str, str]:
    """{header: value} 중 비어있지 않은 상위 n개를 80자로 절단(job 크기 상한). SITS/STS 내용 캡처 공용."""
    out: Dict[str, str] = {}
    for k, v in list((d if isinstance(d, dict) else {}).items()):  # 비-dict(리스트 등) 방어 — 유닛루프 크래시 차단
        sv = str(v).strip()
        if not sv:
            continue
        out[str(k)[:60]] = sv[:80]
        if len(out) >= n:
            break
    return out


def _normTc(s: Any) -> str:
    r"""TC/요구 ID 정규화 — 내부 공백 전부 제거 + 대문자.

    프론트 `_normReq`(``replace(/\s+/g,'').toUpperCase()``) 및 백엔드 `_normalize_req_id`와 **동일**해야
    doc_content(sts_by_tc/sits_by_tc)의 키가 프론트 `stsTestCases`/`sitsTestCases`(추적 매트릭스 testcase)와
    조인된다. 불일치 시 내용은 조용히 사라지지 않고 프론트에서 '미파싱'으로 정직 표기된다."""
    return "".join(str(s or "").split()).upper()


def _load_sits_fn_chains(
    linked_doc: str, flagged_fns: List[str], warn_sink: Optional[List[str]] = None,
    content_sink: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[str]]:
    """Return {entry_fn: [label, ...]} from the SITS vectorcast intermediate JSON.

    content_sink(선택): 제공되면 {_normTc(tc_id): {call_chain, sub_cases:[{precondition, inputs, expected}]}}로
    통합 TC 실 내용을 채운다(문서 카드용, TC-ID 키). 프론트가 TC-ID로 조인하므로 entry_fn 매칭과 무관하게
    전체 TC를 담는다. 회귀 반환({entry_fn:[label]})은 불변(순수 additive).

    intermediate(`<sits>_vectorcast.json`)는 SITS 빌더가 생성한다 — cloudium이면 worker 경유로
    읽는다(직접 FS 금지). cloudium은 읽기전용이라 intermediate 자체가 없을 수 있고, 그때의 0은
    정당하다(사유는 warn_sink)."""
    if not linked_doc:
        return {}

    def _warn(msg: str) -> None:
        if warn_sink is not None:
            warn_sink.append(msg)

    try:
        stem = Path(linked_doc).stem
        intermediate = str(Path(linked_doc).with_name(stem + "_vectorcast.json"))
    except Exception:
        return {}
    try:
        from backend.services.file_resolver import get_resolver
        raw = get_resolver().read_bytes(intermediate)
    except FileNotFoundError:
        _warn("회귀 체인: SITS VectorCAST 중간파일 미생성(SITS 빌더 미실행) — 통합 체인 미집계")
        return {}
    except (PermissionError, OSError):
        _warn("회귀 체인: SITS 중간파일 접근 실패(cloudium worker) — 통합 체인 미집계")
        return {}
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        _warn("회귀 체인: SITS 중간파일 JSON 파싱 실패 — 통합 체인 미집계")
        return {}
    fn_set = {fn.strip().lower() for fn in flagged_fns}
    result: Dict[str, List[str]] = {}
    _integrations = (data.get("integrations") if isinstance(data, dict) else None) or []
    _itc_exc = 0  # malformed 통합케이스(예외) 개수 — 격리하고 사유만 표면화(전체 체인집합 유실 방지)
    for itc in _integrations:
        try:
            if not isinstance(itc, dict):
                _itc_exc += 1
                continue
            entry = str(itc.get("entry_fn") or "").strip()
            chain = str(itc.get("call_chain") or "").strip()
            tc_id = str(itc.get("tc_id") or "")
            if entry.lower() in fn_set:
                label = f"{tc_id}: {chain}" if tc_id else chain
                if label:
                    result.setdefault(entry, []).append(label)
            # 문서 카드용 실 내용(TC-ID 키) — sub_cases의 precondition/inputs/expected 보존. 프론트가 TC-ID로
            # 조인하므로 entry_fn 매칭과 무관하게 전체 TC를 담는다(문서 소규모, 총량 800 캡). 회귀 result는 불변.
            _nk = _normTc(tc_id)
            if content_sink is not None and _nk and len(content_sink) < 800:
                _subs = [
                    {
                        "precondition": str(sc.get("precondition") or "").strip()[:200],
                        "inputs": _cap_kv(sc.get("inputs")),
                        "expected": _cap_kv(sc.get("expected")),
                    }
                    for sc in (itc.get("sub_cases") or [])[:3] if isinstance(sc, dict)
                ]
                content_sink[_nk] = {"call_chain": chain[:200], "sub_cases": _subs}
        except Exception:  # noqa: BLE001 — 한 통합케이스의 기형 데이터가 전체 체인집합을 무너뜨리지 않게 격리  # silent-ok(_itc_exc로 집계·표면화)
            _itc_exc += 1
            continue
    if _itc_exc:
        _warn(f"회귀 체인: SITS 통합케이스 {_itc_exc}건 파싱 예외로 건너뜀 — 통합 체인 과소 가능(데이터 형식 확인)")
    # SUTS 로더(_load_suts_fn_tcs)와 대칭 — 중간파일에 통합케이스는 있는데 영향 함수와 entry_fn이
    # 하나도 매칭 안 되면 조용한 0 대신 사유를 남긴다(이름 규칙 불일치 등, silent-0 방지).
    if not result and fn_set and _integrations:
        _warn("회귀 체인: SITS 통합케이스는 있으나 영향 함수와 entry_fn이 매칭되지 않아 통합 체인 0(이름 규칙 확인)")
    return result


def _load_testspec_by_tc(
    linked_doc: str, warn_sink: Optional[List[str]] = None, doc_label: str = "STS"
) -> Dict[str, Any]:
    """STS/SITS xlsm(bytes)을 표준 파서(`parse_swuts_xlsm`)로 파싱해 TC-ID 키 내용 맵을 반환한다.

    반환: {_normTc(tc_id): {description, precondition, test_method, unit_name, test_action, expected}}
    — 문서 카드용(test_action/expected는 STS 'Test Action(Sequence)'/'Expected Result', 자유텍스트).
    STS는 전용 파서가 없어 이 표준 파서 best-effort로만 도달한다. 시트/라벨 미매칭(ok=False)이면
    과대추정 대신 빈 dict + 사유 warn(정직 '미파싱'). cloudium은 worker(read_bytes) bytes 경유.
    (SITS는 로컬 빌드면 중간 JSON이 더 풍부하므로 이 함수는 그 폴백으로 쓰인다.)"""
    if not linked_doc:
        return {}

    def _warn(msg: str) -> None:
        if warn_sink is not None:
            warn_sink.append(msg)

    try:
        from backend.services.file_resolver import get_resolver
        data = get_resolver().read_bytes(linked_doc)
    except FileNotFoundError:
        _warn(f"{doc_label} 내용: 연동 문서를 찾을 수 없어 TC 내용 미파싱")
        return {}
    except (PermissionError, OSError):
        _warn(f"{doc_label} 내용: 문서 접근 실패(cloudium worker) — TC 내용 미파싱")
        return {}
    except Exception:
        return {}
    if not data:
        return {}
    try:
        from backend.services.swuts_excel_parser import parse_swuts_xlsm
        res = parse_swuts_xlsm(data)
    except Exception:
        _warn(f"{doc_label} 내용: 표준 파서 예외 — TC 내용 미파싱")
        return {}
    if not getattr(res, "ok", False):
        _warn(f"{doc_label} 내용: 표준 파서 미매칭(TC 시트/헤더 라벨 불일치) — TC 내용 미파싱(전용 파서 부재)")
        return {}
    out: Dict[str, Any] = {}
    for tc_id, e in (res.by_tc_id or {}).items():
        nk = _normTc(tc_id)
        if not nk:
            continue
        if len(out) >= 800:
            break
        out[nk] = {
            "description": str(getattr(e, "description", "") or "").strip()[:300],
            "precondition": str(getattr(e, "precondition", "") or "").strip()[:200],
            "test_method": str(getattr(e, "test_method", "") or "").strip()[:60],
            "unit_name": str(getattr(e, "unit_name", "") or "").strip()[:80],
            "test_action": str(getattr(e, "test_action", "") or "").strip()[:300],
            "expected": str(getattr(e, "expected", "") or "").strip()[:300],
        }
    return out


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
    # 파일명에 scm_id 포함 — 실행 락이 scm별이라 서로 다른 프로젝트가 같은 초에 끝날 수 있고,
    # 그때 검토 산출물(ISO 26262 FLAG 증거)이 조용히 덮어써진다.
    _scm = "".join(
        c if (c.isalnum() or c in {"-", "_"}) else "_" for c in str(getattr(trigger, "scm_id", "") or "")
    ).strip("_")
    _stem = f"{target}_review_required_{_ts()}" + (f"_{_scm}" if _scm else "")
    out_path = review_dir / f"{_stem}.md"
    _n = 1
    while out_path.exists():
        out_path = review_dir / f"{_stem}_{_n}.md"
        _n += 1
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
    """콜그래프 모듈 스코핑용 모듈명 = **파일이 속한 디렉터리**.

    ⚠ by_name["module_name"]은 uds_generator가 `Path(file).stem`(=파일명)으로 채운다. 그걸 모듈로
    쓰면 same_module_only가 사실상 '같은 파일'이 되고, fatten이 이미 변경 파일의 전 함수를 seed로
    넣으므로 **간접 영향이 구조적으로 항상 0**이 된다(다른 파일의 호출자가 UDS/SUTS/STS/SDS에서
    통째로 누락 = under-report). 원래 의도(폴더=모듈)는 아래 폴백이 증명한다 — 디렉터리를 우선한다.
    """
    file_path = str(info.get("file") or "").strip()
    if file_path:
        return Path(file_path.replace("\\", "/")).parent.name.lower()
    return str(info.get("module_name") or "").strip().lower()


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
            # ⚠ 모듈 미해결(한쪽이라도 module_name 없음)이면 엣지를 **유지**한다(fail-open).
            #   이는 의도된 안전측 선택 — fail-closed로 바꾸면 모듈을 모르는 함수의 콜엣지가 통째로
            #   사라져 영향 범위가 줄어든다(under-report = ISO 26262에서 위험한 방향). 대신 same-module
            #   집합에 소수의 cross-module 엣지가 섞일 수 있다(과대보고 = 안전). 절대 fail-closed로
            #   "고치지" 말 것.
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
    stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    direct = sorted(seeds)
    if not seeds:
        return {"direct": [], "indirect_1hop": [], "indirect_2hop": [], "paths": {}}

    visited = set(seeds)
    frontier = set(seeds)
    indirect_1: Set[str] = set()
    indirect_2: Set[str] = set()
    # 간접영향 근거(사용자 요청): neighbor를 처음 발견시킨 경유 노드(parent)를 보존해 "왜 간접인지"
    # (변경함수 → ... → 이 함수)를 표면화한다. frontier 순회 순서가 결정적이지 않을 수 있어
    # setdefault로 첫 발견만 채택(안정). direct는 parent 없음. 순수 additive(리스트 반환 불변).
    parent: Dict[str, str] = {}

    truncated_at: int = 0  # >0이면 그 depth까지만 탐색하고 중단(이후 hop은 '미계산')
    for depth in range(1, max_hop + 1):
        next_frontier: Set[str] = set()
        for func in sorted(frontier):  # 결정적 parent 선택(정렬 순회)
            for neighbor in sorted(neighbors.get(func, set())):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                next_frontier.add(neighbor)
                parent.setdefault(neighbor, func)  # 첫 발견 경유 노드
                if depth == 1:
                    indirect_1.add(neighbor)
                elif depth == 2:
                    indirect_2.add(neighbor)
        if len(visited) > max_impacted_functions:
            # ⚠ 상한 초과 → 다음 depth 미탐색. 변경 함수가 많으면(예: seeds 638 > 상한 50) depth1
            # 직후 항상 여기서 끊겨 indirect_2hop이 **영구히 빈 배열**이 된다. 빈 배열은 "2-hop 영향
            # 없음"이 아니라 "미계산"이므로, 그 사실을 stats로 표면화해야 안전 검토자가 오독하지 않는다.
            if depth < max_hop:
                truncated_at = depth
            break
        frontier = next_frontier
        if not frontier:
            break

    if stats is not None:
        stats["truncated"] = truncated_at > 0
        stats["truncated_at_hop"] = truncated_at
        stats["visited"] = len(visited)
        stats["max_impacted_functions"] = max_impacted_functions
    # 간접영향 근거 맵 — 각 간접 함수의 경유 노드(via=직전 발견자)와 seed(via 역추적한 최초 변경함수).
    # seed는 parent 사슬을 seeds에 닿을 때까지 따라간다(cycle 방어: 최대 max_hop+1회). "왜 간접인지"를
    # 프론트/AI가 표시하도록 job에 실린다(무향그래프라 '경유'로만 표기, caller/callee 단정 안 함).
    paths: Dict[str, Dict[str, Any]] = {}
    for _fn, _hop in [(f, 1) for f in indirect_1] + [(f, 2) for f in indirect_2]:
        _via = parent.get(_fn)
        _seed = _via
        _steps = 0
        while _seed is not None and _seed not in seeds and _steps <= max_hop + 1:
            _seed = parent.get(_seed)
            _steps += 1
        paths[_fn] = {"hop": _hop, "via": _via or "", "seed": (_seed if _seed in seeds else (_via or ""))}
    return {
        "direct": sorted(direct),
        "indirect_1hop": sorted(indirect_1),
        "indirect_2hop": sorted(indirect_2),
        "paths": paths,
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
    # 동일 이름 함수가 여러 파일에 정의된 경우(by_name["files"]) **모든** 정의 파일을 매칭 대상에
    # 넣는다. 과거엔 last-wins로 남은 file 하나만 봐서, 다른 사본이 있는 파일이 변경돼도 그 함수가
    # full_hits에 안 잡히고(basename 폴백은 `full_hits or base_hits`로 무시됨) **통째로 누락**됐다
    # (예: Generated_Code/EEPROM.c 변경 시 eeprom_setbyte 등 5개 — 안전 관련 under-report).
    norm_files: List[Tuple[str, str]] = []
    for func_name, info in by_name.items():
        _fs = info.get("files") or ([info.get("file")] if info.get("file") else [])
        for _f in _fs:
            _fp = str(_f or "").replace("\\", "/").lower()
            if _fp:
                norm_files.append((func_name, _fp))
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


def _collect_signature_changes(trigger, meta, entry, diff_text: str = "", diff_sink: Optional[List[str]] = None) -> Dict[str, Dict[str, str]]:
    """함수별 시그니처 이전/이후 선언 원문을 추출한다(UI '변경 상세' 원문 표시용).

    - diff_text가 주어지면(A-3에서 이미 받은 svn A:B unified diff) 재-fetch 없이 그것으로 추출한다
      (fetch-once — 623KB blob을 분류와 시그니처 추출이 공유).
    - svn revision-range(baseline A ↔ build B): `svn diff -r A:B <scm_url>` 전체 unified diff 1회.
    - 로컬 git/svn working-copy: 변경 파일별 unified diff(상한 60개).
    - diff_sink(선택): 제공되면 여기서 실제로 받은 unified diff 원문을 append한다 — 호출측이 이를
      function_diffs 추출에 재사용(로컬 경로 "원문 절단" 해소, 재-diff 없이 blob 공유).
    best-effort — 실패/미지원이면 빈 dict(영향 분석 자체엔 무영향, UI 원문만 미표시).
    """
    from workflow.delta_update import extract_signature_changes
    if diff_text:
        return extract_signature_changes(diff_text)
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
                _out = d.get("output") or ""
                if diff_sink is not None and _out:
                    diff_sink.append(_out)
                return extract_signature_changes(_out)
        except Exception as exc:  # noqa: BLE001 — best-effort, 실패 흡수
            logger.debug("svn_diff_unified signature extraction failed: %s", exc)
        return {}
    # (2) 로컬 git/svn working-copy diff: 변경 파일별(상한, 파일 단위 격리)
    src = str(getattr(entry, "source_root", "") or getattr(trigger, "source_root", "") or "").strip()
    scm_type = str(getattr(trigger, "scm_type", "") or "").lower()
    changed_files = list(getattr(trigger, "changed_files", None) or [])
    if src and scm_type in ("git", "svn") and changed_files:
        from workflow.delta_update import _run_unified_diff, _signature_change_rank
        merged: Dict[str, Dict[str, str]] = {}
        for fp in changed_files[:60]:
            # 파일 단위 try/except — 개별 파일 timeout/권한 오류가 앞서 성공한 파일 원문을
            # 폐기하지 않게 한다(sibling classify_changed_functions와 동일 패턴).
            try:
                dt = _run_unified_diff(src, base_ref=getattr(trigger, "base_ref", ""), scm_type=scm_type, file_path=fp)
                if diff_sink is not None and dt:
                    diff_sink.append(dt)
                for fn, sig in extract_signature_changes(dt or "").items():
                    # rank-aware 병합 — 동명 static 함수가 여러 파일에 있을 때 무변화 파일이 '나중에'
                    # 와도 실제 변경(before!=after)을 덮지 않는다. 과거 setdefault().update()는 last-wins라
                    # 파일 순서에 따라 실변경을 무변화로 가려 SIGNATURE인데 '원문 미확보'로 표시됐다
                    # (whole-blob 경로 cross-file 마스킹과 동형 — _signature_change_rank 단일 출처).
                    _prev = merged.get(fn)
                    if _prev is None or _signature_change_rank(sig) > _signature_change_rank(_prev):
                        merged[fn] = sig
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
        # ── A: svn revision-range 라인 diff 기반 정밀 변경분류(과대보고 축소 + 정확 kind) ──
        # 원격 svn diff(-x -p)는 로컬 working-copy가 없어도(cloudium 포함) 동작한다 —
        # _collect_signature_changes가 이미 같은 diff를 받으므로 여기서 1회 받아 A-5에서 공유한다.
        # 실패/미접근/역방향/컨텍스트 없음 → _precise_types=None(기존 파일단위 보수 경로 유지,
        # 조용한 narrowing 절대 없음 — 정밀분류는 성공했을 때만 적용하는 순수 상향).
        _precise_types: Dict[str, str] | None = None
        _precise_diff_text = ""
        _line_classified_files: Set[str] = set()
        _narrow_removed_n = 0  # A-4에서 정밀 narrowing으로 제거한 함수 수(감사/경고용)
        _narrow_removed_list: List[str] = []  # 제거 함수 전체 목록(durable audit 추적성 — ISO 26262)
        # 함수별 증거 출처: "line"=실제 라인변경 확인 / "file_fatten"=파일단위 보수 포함(라인변경 미확인).
        # 프론트가 function_diffs 부재로 '증거 없음'을 추론하던 것을 백엔드 사실로 대체(단일 출처).
        _fn_evidence: Dict[str, str] = {}
        # 이름충돌(동명 다른 함수) 집합 — coverage_gap이 서로 다른 copy를 전역 max로 병합해 gap을
        # 은폐하지 않도록 넘긴다(source parse 성공 시 아래 overlay에서 채움; 실패 시 빈 집합).
        _collision_names: Set[str] = set()
        _base_r = str(_meta.get("baseline_revision") or "").strip()
        _build_r = str(_meta.get("build_revision") or "").strip()
        _scm_url = str(getattr(entry, "scm_url", "") or "").strip()
        if (
            _changed_files_source == "svn_revision_range"
            and _base_r.isdigit() and _build_r.isdigit() and int(_base_r) < int(_build_r)
            and _scm_url
        ):
            try:
                from backend.services.local_service import svn_diff_unified
                from backend.services.scm_registry import resolve_scm_credentials
                from workflow.delta_update import (
                    classify_changed_functions_from_diff_text,
                    diff_has_function_context,
                )
                _u, _pw, _ = resolve_scm_credentials(scm_id=trigger.scm_id)
                _d = svn_diff_unified(repo_url=_scm_url, rev_a=_base_r, rev_b=_build_r, username=_u, password=_pw)
                _out = _d.get("output") or ""
                if int(_d.get("rc", 1)) == 0:
                    # rc==0이면 A-5(_collect_signature_changes)와 공유해 재fetch를 막는다(W1) —
                    # bare여도 시그니처 추출(+/- 선언 라인)엔 무해.
                    _precise_diff_text = _out
                    # positive-context 가드: -x -p 컨텍스트가 실제 붙어야 함수단위 분류가 신뢰 가능.
                    # 컨텍스트가 전무(구 svn이 -p 무시)하면 정밀분류를 건너뛰어 보수 경로 유지.
                    if diff_has_function_context(_out):
                        _precise_types, _line_classified_files = classify_changed_functions_from_diff_text(_out)
            except Exception as _pexc:  # noqa: BLE001 — 정밀분류 실패는 보수 경로로 폴백
                logger.debug("precise line classification skipped: %s", _pexc)
                _precise_types = None
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

        # warnings: ASIL 보강/UDS·SDS 손상 경고를 이 블록에서부터 append하므로 여기서 초기화한다
        # (과거엔 1762에서 정의 → ASIL 블록이 warn_sink=warnings를 못 써 UnboundLocalError). 이후
        # 코드가 이 단일 리스트에 계속 append하고 result에 실린다(재정의 금지 — 재정의 시 ASIL 경고 유실).
        warnings: List[str] = []
        _asil_uds_enriched = 0  # UDS 문서에서 ASIL을 보강한 함수 수(소스 주석 미기재분 — 아래서 채움)
        _asil_sds_enriched = 0  # UDS로 해석 안 된 함수를 SDS ASIL로 폴백 보강한 수
        if entry and entry.source_root:
            if callable(on_progress):
                on_progress("impact_analysis", "영향 범위를 계산 중입니다.", {"changed_functions": len(changed_types)})
            sections = _load_source_sections(entry.source_root)
            by_name_raw = sections.get("function_details_by_name", {}) or {}
            by_name = {str(k).strip().lower(): v for k, v in by_name_raw.items() if isinstance(v, dict)}
            # 동일 이름 함수의 다중 정의(파일 간 충돌)를 by_name에 얹는다. by_name은 last-wins라
            # 한 사본의 file/asil만 남아 (a) 다른 파일 변경 시 그 함수를 통째로 놓치고(under-report),
            # (b) 낮은 ASIL로 오판(escalation·MC/DC 게이트 무력화)한다.
            # ⚠ sections는 _load_source_sections가 deepcopy로 돌려준 **이 실행 전용 사본**이므로
            #    여기서 값을 수정해도 문서 생성 경로(function_details 원본)에는 영향이 없다.
            for _cn, _ce in (sections.get("function_collisions") or {}).items():
                _collision_names.add(str(_cn).strip().lower())  # coverage worst-copy 병합용
                _ci = by_name.get(str(_cn).strip().lower())
                if not isinstance(_ci, dict) or not isinstance(_ce, dict):
                    continue
                _cf = [str(f) for f in (_ce.get("files") or []) if str(f or "").strip()]
                if _cf:
                    _ci["files"] = _cf
                if _asil_rank(_ce.get("asil")) > _asil_rank(_ci.get("asil")):
                    _ci["asil"] = str(_ce.get("asil") or "")  # 안전측 — 두 사본 중 높은 등급
            # C 소스에 @asil 주석이 없어도 링크된 UDS(함수별 ASIL)로 보강한다 — cloudium U:\는 워커 경유.
            # (소스 ASIL이 있는 함수는 유지, 빈 함수만 채움 → _asil_of·에스컬레이션·커버리지 타깃에 반영)
            _asil_uds_enriched, _asil_still_missing = _enrich_asil_from_uds(
                by_name, getattr(getattr(entry, "linked_docs", None), "uds", "") or "",
                warn_sink=warnings,
            )
            # UDS 보강 후에도 남은 미상만 SDS ASIL(SwCom/인터페이스 함수)로 폴백 보강 — UDS 손상/부재
            # 견고화. 소스 > UDS > SDS, TBD만 채움·등급 낮추기 없음(안전측).
            _asil_sds_enriched, _asil_still_missing = _enrich_asil_from_sds(
                by_name, getattr(getattr(entry, "linked_docs", None), "sds", "") or "",
                warn_sink=warnings,
            )
            # 그래도 남은 미상은 SwUDS 함수의 소속 SwCom(Related ID) → SDS 컴포넌트 ASIL로 상속 보강
            # (ISO 26262 컴포넌트 ASIL 상속 — 가장 약한 폴백). SwUDS가 신규 안전함수의 ASIL 칸을 N/A로
            # 비워둔 경우(문서 등급 누락) 소속 컴포넌트 등급으로 채운다. 상향만·등급 낮추기 없음(안전측).
            _asil_swcom_enriched, _asil_still_missing = _enrich_asil_from_swcom(
                by_name,
                getattr(getattr(entry, "linked_docs", None), "uds", "") or "",
                getattr(getattr(entry, "linked_docs", None), "sds", "") or "",
                warn_sink=warnings,
            )
            # resolve(fatten) 전에 '실제로 지목된' 함수를 보존 — 로컬 diff 경로의 라인증거 판별용.
            # (cloudium/editType 경로의 키는 함수명이 아니라 파일 기반이라 line 증거로 쓰지 않는다.)
            _pre_resolve_lc = {str(k).strip().lower() for k in changed_types}
            _pre_resolve_is_line = _classification_granularity == "line"
            changed_types = _resolve_changed_types_to_functions(
                changed_types, trigger.changed_files, by_name, edit_types=edit_types
            )
            # known_funcs 검증을 붙여 정밀분류를 재수행 — narrowable 게이트가 매크로/타입 오귀속
            # (`FUNC(...)`, `u8 (*pf)(`)을 실제 함수로 오인해 파일 전체 함수를 제거(under-report)하는
            # 것을 막는다. by_name은 여기서야 사용 가능하므로 이 시점에 재평가한다(regex 1패스).
            if _precise_types is not None and _precise_diff_text:
                try:
                    _precise_types, _line_classified_files = classify_changed_functions_from_diff_text(
                        _precise_diff_text, set(by_name)
                    )
                except Exception as _rexc:  # noqa: BLE001 — 재평가 실패 시 기존(보수) 결과 유지
                    logger.debug("precise re-classification with known_funcs skipped: %s", _rexc)
            # A-4: post-resolve narrowing — resolve가 변경파일의 전체 함수로 재확장(fatten)한 것을,
            # 라인변경이 검증된 순수 편집 .c(line_classified_files)에서만 실제 라인변경 함수로 좁힌다.
            # 그 외(헤더/매크로·인클루드·모듈스코프 변경 .c)는 fatten 유지(안전측 — 라인변경 없는
            # 함수도 데이터/매크로 결합으로 영향받을 수 있음, hop-BFS는 데이터엣지 미포함). 모든
            # 파일에서 정밀 KIND(SIGNATURE/NEW/DELETE)는 승격해 SDS 자동 FLAG를 복원한다.
            if _precise_types is not None:
                _precise_lower = {str(k).strip().lower(): v for k, v in _precise_types.items()}

                def _in_line_classified(_fn: str) -> bool:
                    _info = by_name.get(_fn) or {}
                    # 동일 이름 함수가 여러 파일에 정의됐으면 어느 사본 기준인지 확정 불가 →
                    # narrow(제거)하면 다른 사본이 조용히 누락될 수 있다(under-report). 보수적으로
                    # fatten 유지(= 절대 제거하지 않음).
                    if len(_info.get("files") or []) > 1:
                        return False
                    _f = str(_info.get("file") or "").replace("\\", "/").lower()
                    if not _f:
                        return False
                    # ⚠ 경계 없는 endswith는 다른 파일을 오매칭한다: "…/myapp/led.c".endswith("app/led.c")
                    # == True → 그 파일이 line-classified로 오판돼, 라인변경 없다고 함수가 **제거**된다
                    # (under-report — 안전하지 않은 방향). 경로 구분자 경계를 강제한다.
                    return any(_f == _p or _f.endswith("/" + _p) for _p in _line_classified_files)

                _narrowed: Dict[str, str] = {}
                for _fn, _kind in changed_types.items():
                    _pk = _precise_lower.get(_fn)
                    if _in_line_classified(_fn):
                        if _pk is not None:
                            _narrowed[_fn] = _pk  # 라인변경된 함수만, 정밀 kind
                            _fn_evidence[_fn] = "line"
                        # else: 순수 편집 파일에서 라인변경 없음 → 제거(진짜 무영향)
                    else:
                        _narrowed[_fn] = _pk if _pk is not None else _kind  # fatten 유지 + kind 승격
                        # 함수별 증거 출처(provenance) — 프론트가 function_diffs 유무로 '증거 없음'을
                        # 추론하던 것을 대체한다(그 추론은 diff 400KB 절단·local-diff 경로에서 실제
                        # 변경 함수를 '파일영향'으로 오분류해 기본 집계에서 숨길 수 있었다).
                        _fn_evidence[_fn] = "line" if _pk is not None else "file_fatten"
                for _fn, _k in _precise_lower.items():  # 신규/삭제 함수(baseline 부재분) 편입
                    if _k in ("NEW", "DELETE") and _fn not in _narrowed:
                        _narrowed[_fn] = _k
                        _fn_evidence[_fn] = "line"
                # X8: 축소(제거)된 함수 감사 추적 — silent 제거 금지(ASIL C/D 리뷰 추적성).
                _removed = sorted(set(changed_types) - set(_narrowed))
                _narrow_removed_n = len(_removed)
                _narrow_removed_list = _removed  # durable audit 추적성(전체 목록)
                if _removed:
                    logger.info(
                        "impact precise-narrow: removed %d function(s) from %d line-classified file(s): %s",
                        _narrow_removed_n, len(_line_classified_files),
                        ", ".join(_removed[:30]) + (" ..." if len(_removed) > 30 else ""),
                    )
                changed_types = _narrowed
                _classification_granularity = "line"
            else:
                # 정밀분류 미적용(cloudium/editType 또는 로컬 diff) — resolve가 파일 전체 함수로
                # fatten했으므로 '라인증거'는 resolve 전에 지목된 함수만이다. 나머지는 file_fatten.
                for _fn in changed_types:
                    _fn_evidence[_fn] = (
                        "line" if (_pre_resolve_is_line and _fn in _pre_resolve_lc) else "file_fatten"
                    )
            # granularity 정직화: 스칼라 하나로는 "일부 line·일부 fatten" 상태를 표현할 수 없다.
            # (과거엔 로컬 경로가 fatten인데도 'line'이라 단정 → 프론트 '(보수 추정)' 경고가 꺼졌다.)
            _fatten_n = sum(1 for _v in _fn_evidence.values() if _v == "file_fatten")
            _line_n = sum(1 for _v in _fn_evidence.values() if _v == "line")
            if _fatten_n and _line_n:
                _classification_granularity = "mixed"
            elif _fatten_n and not _line_n:
                _classification_granularity = "file"
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

        # BFS 탐색 상한 = seeds가 있어도 최소 2-hop을 계산할 여지를 두되 폭주는 막는다.
        # seeds가 승격 임계보다 많으면(cross-module 대량 변경) seeds*4 근방까지 허용(hard cap 이내).
        # → indirect_1hop/2hop이 seeds 규모 때문에 조기 절단되지 않는다(2hop 미계산 상시화 해소).
        _seed_n = len(changed_types)
        _bfs_cap = min(options.bfs_hard_cap, max(options.max_impacted_functions, _seed_n * 4))
        _bfs_stats: Dict[str, Any] = {}
        impact_groups = _hop_limited_impact(
            set(changed_types),
            neighbors,
            max_hop=options.max_hop,
            max_impacted_functions=_bfs_cap,
            stats=_bfs_stats,
        )
        sits_impact_groups: Dict[str, List[str]] | None = None
        if neighbors_cross is not None:
            sits_impact_groups = _hop_limited_impact(
                set(changed_types),
                neighbors_cross,
                max_hop=options.max_hop,
                max_impacted_functions=_bfs_cap,
            )
        impacted_total = len(_impacted_union(impact_groups))
        # (warnings는 위 ASIL 블록에서 이미 초기화됨 — 여기서 재정의하면 ASIL 경고가 유실된다.)
        # 콜그래프 탐색이 상한에서 끊겼으면 빈 hop이 '영향 없음'이 아니라 '미계산'임을 명시.
        if _bfs_stats.get("truncated"):
            _tr_hop = _bfs_stats.get("truncated_at_hop") or 0
            warnings.append(
                f"콜그래프 탐색 중단: 영향 함수 {_bfs_stats.get('visited')}개가 상한"
                f"({_bfs_stats.get('max_impacted_functions')})을 초과해 {_tr_hop}-hop까지만 계산했습니다 — "
                f"{_tr_hop + 1}-hop 이상은 '영향 없음'이 아니라 '미계산'입니다(빈 목록 오독 주의)."
            )
        if _asil_uds_enriched:
            warnings.append(
                f"ASIL 보강: 소스 주석에 ASIL이 없는 함수 {_asil_uds_enriched}개를 UDS 문서에서 해석(cloudium 워커 경유)"
            )
        if _asil_sds_enriched:
            warnings.append(
                f"ASIL 보강: UDS로 해석 안 된 함수 {_asil_sds_enriched}개를 SDS(SwCom/인터페이스 ASIL)로 폴백 해석"
            )
        # AUTO를 검토(FLAG)로 강등할 '실질적' 사유만 모은다 — 정보성 경고(Jenkins revision/SITS
        # cross 안내 등)는 AUTO를 봉쇄하지 않는다(과보수 회귀 방지). 한도 초과·ASIL 에스컬레이션만.
        promote_to_review = False
        _promote_thr = options.review_promote_threshold or options.max_impacted_functions
        if impacted_total > _promote_thr:
            promote_to_review = True
            warnings.append(
                f"impacted function count exceeded limit ({impacted_total}>{_promote_thr}); promote to review"
            )
        if sits_impact_groups is not None:
            sits_total = len(_impacted_union(sits_impact_groups))
            if sits_total > impacted_total:
                warnings.append(
                    f"SITS cross-module impact ({sits_total}) exceeds same-module impact ({impacted_total}); SITS uses cross-module set"
                )
            if sits_total > _promote_thr:
                promote_to_review = True
                warnings.append(
                    f"SITS cross-module impacted ({sits_total}) exceeded limit ({_promote_thr}); promote to review"
                )
        # Jenkins changeSet로 파일집합을 받은 경우의 변경 '유형' 분류 출처를 투명하게 알린다.
        # editType이 있으면 빌드 changeSet 기준, 없으면 로컬 working-copy diff 기준.
        # 정직 고지(X7): diff가 없어 SIGNATURE를 BODY로 분류 → ACTION_MATRIX상 BODY는 sds='-'
        # 이므로, .c만 바뀐 인터페이스(시그니처) 변경은 SDS 검토가 자동 FLAG되지 않을 수 있다
        # (.h가 changeSet에 함께 오면 sds/sts FLAG 가드로 커버됨). ASIL 관련 인터페이스는 수동 확인.
        if _precise_types is not None:
            # 정밀 라인 분류 적용됨 — 시그니처/신규/삭제가 함수단위로 판별됨(위 보수 경고 대체).
            warnings.append(
                f"라인 diff 기반 정밀 변경분류 적용(svn diff -r {_base_r}:{_build_r} -x -p) — "
                f"함수단위 kind(SIGNATURE/NEW/DELETE) 판별. 안전이 증명된 {len(_line_classified_files)}개 .c"
                f"(순수 본문편집·전 hunk 함수귀속·전처리/top-level 변경 없음)에서 라인변경 없는 {_narrow_removed_n}개 함수 제외"
                "(감사 로그 기록). 그 외 변경 .c(전처리·전역var·배열·typedef 등 top-level 변경)는 라인변경 없는 함수도 "
                "데이터/매크로 결합으로 영향 가능하므로 파일단위 보수 분류를 유지(안전측 — under-report 방지)."
            )
        elif _is_authoritative_remote and edit_types:
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
            # 다중정의 함수는 files[]에 정의 파일이 전부 들어 있다 — file 하나만 보면 그 함수가
            # '유일하게' 정의된 파일을 놓쳐 "baseline 인덱스에 없음" 허위 경고가 난다
            # (_resolve_changed_types_to_functions와 동일한 확장을 써야 일관).
            _bn_files = []
            for v in by_name.values():
                _vi = v or {}
                for _f in (_vi.get("files") or ([_vi.get("file")] if _vi.get("file") else [])):
                    _fp = str(_f or "").replace("\\", "/").lower()
                    if _fp:
                        _bn_files.append(_fp)

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
        # 소스 인덱스(by_name)가 비었는데 변경파일이 있으면 함수 해석이 불가능하다. 이때
        # _resolve_changed_types_to_functions는 조기 반환하고 **파일명(stem)이 그대로 '함수'처럼**
        # impact.direct/function_meta/coverage/actions.functions로 흘러간다(데이터 날조).
        # 과거엔 이 경고가 cloudium에서만 떠서, 로컬 배포에서 source_root 경로가 없으면(가장 흔한
        # 배포 실수) **완전히 조용히** 파일명이 함수로 보고됐다 → 모드 무관 경고 + 검토 승격.
        if not by_name and trigger.changed_files:
            promote_to_review = True
            _reason = "cloudium worker read 실패 가능" if cloudium else "source_root 경로 부재/파싱 실패 가능"
            warnings.append(
                f"소스 인덱스 0건({_reason}) — 함수 해석 불가로 **파일명이 함수처럼 표시**될 수 있습니다. "
                "영향 결과(함수 목록·ASIL·커버리지·회귀시험)를 신뢰하지 말고 source_root/워커를 먼저 확인하십시오."
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
        # 로컬 diff 경로(_precise_diff_text 없음)에서 시그니처 추출이 뽑는 per-file diff 원문을 여기 모아
        # function_diffs에도 공유한다(fetch-once) — 로컬 line-classified 함수가 diff 원문을 못 받아
        # "원문 절단"으로 표시되던 것을 해소(재-diff 없이 시그니처·본문 두 소비자가 같은 blob 사용).
        _local_diff_parts: List[str] = []
        if changed_types:
            _ct_by_lower = {str(k).strip().lower(): k for k in changed_types}
            try:
                # A-5: A-3에서 이미 받은 diff를 재사용(fetch-once) — 없으면 종전대로 자체 fetch.
                _sig_map = _collect_signature_changes(trigger, _meta, entry, diff_text=_precise_diff_text, diff_sink=_local_diff_parts)
            except Exception as _sig_exc:  # noqa: BLE001 — 원문 보강 실패는 분석을 막지 않음
                logger.debug("change_details extraction failed: %s", _sig_exc)
                _sig_map = {}
            for _fn, _sig in (_sig_map or {}).items():
                _actual = _ct_by_lower.get(str(_fn).strip().lower())
                if _actual is None:
                    continue  # 변경유형에 안 잡힌 함수는 잡음 — 제외
                _before = str(_sig.get("before") or "").strip()
                _after = str(_sig.get("after") or "").strip()
                # 이전==이후(둘 다 존재·선언 동일 — 재정렬/이동)면 UI 원문 표시가 불필요하므로
                # change_details에 넣지 않는다(모달이 '변화 없는 시그니처'를 렌더하지 않도록).
                # 분류 강등(SIGNATURE→BODY)은 여기서 하지 않는다: _sig_map은 파일 미분할 전체 blob
                # 기준이라 동명 static 함수가 다른 파일에 있으면 한 파일 값이 다른 파일 함수를
                # 오강등한다(C2 under-report). 변경유형은 classify_changed_functions_from_diff_text가
                # 파일 스코프로 이미 정확히 판정(same→BODY/changed·unknown→SIGNATURE)하므로 신뢰한다.
                if _before and _after and _before == _after:
                    continue
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

        # AI 설명용 함수별 본문 diff 원문 — BODY 등 선언 미변경 함수도 실제 코드 변경(hunk)을 근거로
        # 제공해, Gemini가 '추정' 대신 실제 변수/로직 기반의 구체 문서 지침을 생성하도록 한다.
        function_diffs: Dict[str, str] = {}
        _fd_stats: Dict[str, Any] = {}
        # 정밀 diff(svn A:B)가 없으면 로컬 per-file diff(위 fetch-once)를 폴백으로 사용해 함수별 본문
        # 원문을 채운다 — evidence='line'인데 원문이 없어 "원문 절단"으로 표시되던 로컬 경로 해소.
        _fd_source = _precise_diff_text or "".join(_local_diff_parts)
        if _fd_source:
            try:
                from workflow.delta_update import extract_function_diffs
                function_diffs = extract_function_diffs(_fd_source, stats=_fd_stats)
            except Exception as _fd_exc:  # noqa: BLE001 — 원문 보강 실패는 분석을 막지 않음
                logger.debug("function_diffs extraction failed: %s", _fd_exc)
                warnings.append("본문 diff 원문 추출 실패 — 상세 모달의 코드 근거가 비어 있을 수 있습니다(분석은 계속).")
        if _fd_stats.get("truncated"):
            # 전체 상한 초과로 일부 함수의 본문 diff가 생략됨. 프론트가 diff 부재를 '증거 없음'으로
            # 오독하지 않도록 명시(evidence 필드가 1차 방어지만 표시도 정직하게).
            warnings.append(
                f"본문 diff 원문이 크기 상한을 넘어 {_fd_stats.get('omitted')}개 함수의 코드 근거가 생략됐습니다 "
                "— '변경 없음'이 아니라 '원문 미수록'입니다(변경 판정은 evidence 기준)."
            )

        # 파일레벨 원문 폴백(#3): 함수 자체 diff가 없는 함수(파일영향/원문 절단)가 모달에서 '파일 전체
        # 변경 보기'로 그 파일의 구조 변경(전처리·전역·prototype 등 fatten 유발 지점)을 확인하게 한다.
        # 순수 표시용 additive — changed_types/evidence/impact 집합/ASIL 무영향.
        file_diffs: Dict[str, str] = {}
        if _fd_source:
            try:
                from workflow.delta_update import extract_file_diffs
                file_diffs = extract_file_diffs(_fd_source)
            except Exception as _fdx_exc:  # noqa: BLE001 — 폴백 원문 실패는 분석을 막지 않음
                logger.debug("file_diffs extraction failed: %s", _fdx_exc)

        # 포맷/이동만(의미 변경 없음) 함수 직접변경→파일영향 강등(사용자 요청 A안): 본문 diff가 코드
        # 이동/공백/포맷만인 함수는 실제로 안 바뀌었으므로 evidence를 line→file_fatten으로 재분류하고
        # 자체 diff를 드롭한다(→ '파일영향' 표시, 기존 '파일영향 숨기기' 필터로 숨김·#3 파일폴백으로 원문
        # 확인). **changed_types(impact 집합)·ASIL 불변 = under-report 0(안전측).** truncated diff는
        # is_noop가 보수적으로 False라 실변경 함수를 절대 강등하지 않는다.
        try:
            from workflow.delta_update import is_noop_function_diff
            _noop_n = 0
            for _fn, _txt in list(function_diffs.items()):
                if _fn_evidence.get(_fn) == "line" and is_noop_function_diff(_txt):
                    _fn_evidence[_fn] = "file_fatten"
                    function_diffs.pop(_fn, None)
                    _noop_n += 1
            if _noop_n:
                warnings.append(
                    f"포맷/이동만(의미 변경 없음) 함수 {_noop_n}개를 '직접 변경'→'파일영향'으로 재분류했습니다 "
                    "(impact 집합·ASIL 불변, '파일영향 숨기기'로 숨김 가능)."
                )
                # granularity 재계산(deep-review W1): 강등이 line→file_fatten을 늘렸으므로 파생 스칼라
                # _classification_granularity를 다시 산출한다(혼재=mixed honesty 불변식 유지 — 위 1925~1930
                # 로직과 동형, sibling 테스트와 정합). signature_distinguished는 이 값 파생이라 자동 정합.
                _fatten_n2 = sum(1 for _v in _fn_evidence.values() if _v == "file_fatten")
                _line_n2 = sum(1 for _v in _fn_evidence.values() if _v == "line")
                if _fatten_n2 and _line_n2:
                    _classification_granularity = "mixed"
                elif _fatten_n2 and not _line_n2:
                    _classification_granularity = "file"
        except Exception as _noop_exc:  # noqa: BLE001 — 강등 실패는 분석을 막지 않음
            logger.debug("format-only downgrade skipped: %s", _noop_exc)

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
                # 증거 출처(단일 출처) — "line"=라인변경 확인 / "file_fatten"=파일단위 보수 포함
                # (라인변경 미확인) / ""=간접 영향 함수(변경 아님). 프론트는 function_diffs 유무로
                # 추론하지 말고 이 값을 쓴다(diff는 400KB 절단·경로별 부재로 증거 프록시가 될 수 없음).
                "evidence": _fn_evidence.get(fn, ""),
                # ASIL 출처 추적성(reviewer W4) — ""=소스 @asil/헤더(또는 미상) / "uds" / "sds"(3순위) /
                # "swcom"(4순위 최약 폴백 — 함수 N/A였으나 소속 SwCom 컴포넌트 등급 상속). 문서/SDS로 채워진
                # 함수는 리뷰어가 별도 재확인하도록 다운스트림(프론트/감사)에 노출.
                "asil_source": str((by_name.get(fn) or {}).get("asil_source") or ""),
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
            # ⚠ 정책 주의(deep-review 지적): 미상은 ASIL B+ escalation과 달리 promote_to_review를
            # 걸지 않는다 — auto_generate 모드에서 '미상(실제로는 C/D일 수 있음)' 변경이 사람 검토
            # 없이 문서 자동 재생성으로 통과할 수 있다. 다만 CLAUDE.md 정책이 "판별 불가 시 QM으로
            # 간주하되 reviewer에게 확인 요청"(=경고, 차단 아님)이므로 현행 유지하고 경고를 강화한다.
            # 자동 차단이 필요하면 아래 한 줄(promote_to_review = True)을 활성화할 것.
            warnings.append(
                f"직접 변경 함수 중 ASIL 미상 {asil_unknown_changed}개 — 안전 등급 수동 확인 필요"
                "(QM 단정 금지). 미상 함수가 실제 ASIL C/D이면 자동 재생성 결과를 반드시 검토하십시오."
            )
        # 회귀시험 선정: 영향 함수 → 기존 SUTS TC / SITS call-chain 집계(재실행 대상 증거).
        _lk = entry.linked_docs if entry else None
        _flagged = sorted(_impacted_all | _changed_set)
        regression_test_set: Dict[str, Any] = {"suts": {}, "sits": {}}
        _suts_content: Dict[str, Any] = {}  # SUTS TC 실내용(문서 카드용) — _load_suts_fn_tcs가 채움
        _sits_by_tc: Dict[str, Any] = {}  # SITS TC 실내용(TC-ID 키) — 중간 JSON에서 _load_sits_fn_chains가 채움
        # SUTS·SITS 회귀집계를 각각 try로 분리 — 한쪽 실패가 다른쪽을 떨어뜨리지 않게. 예외 시 사유를
        # warn으로 표면화(과거 shared try + `except: pass`가 전량 침묵손실 = loader silent-0 정책 위배).
        if _lk and getattr(_lk, "suts", ""):
            try:
                regression_test_set["suts"] = _load_suts_fn_tcs(
                    _lk.suts, _flagged, warn_sink=warnings, content_sink=_suts_content)
            except Exception as exc:  # noqa: BLE001 — best-effort, 없어도 분석은 진행(단 사유 표면화)
                warnings.append(f"회귀 TC: SUTS 재실행 TC 집계 예외로 미집계({exc})")
        if _lk and getattr(_lk, "sits", ""):
            try:
                regression_test_set["sits"] = _load_sits_fn_chains(
                    _lk.sits, _flagged, warn_sink=warnings, content_sink=_sits_by_tc)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"회귀 체인: SITS 재실행 체인 집계 예외로 미집계({exc})")
        regression_test_set["summary"] = {
            "suts_tc_count": sum(len(v) for v in regression_test_set["suts"].values()),
            "sits_chain_count": sum(len(v) for v in regression_test_set["sits"].values()),
            "impacted_function_count": len(_flagged),
            "coverage_target": coverage_target,
            "mcdc_required": mcdc_required,
        }
        # 문서 내용 매칭(예측 대신 실 파싱 내용) — 직접 영향 함수(_changed_set) 스코프. UDS 설명/전역/호출,
        # SUTS TC 실입력·기대값, SDS 컴포넌트 설명을 job에 담아 프론트 카드가 표시. 파일영향(증거 없음)
        # 함수도 문서 내용은 실 파싱본이라 그대로 유효. best-effort(로더 실패=빈 dict, 분석 비차단).
        # sts_by_tc/sits_by_tc는 TC-ID 키(함수 키 아님) — 프론트가 함수별 stsTestCases/sitsTestCases(ID)로
        # 조인한다. uds/suts/sds는 함수명(소문자) 키. 신규 키라 구 job에서도 프론트 ?? {} 폴백으로 안전.
        doc_content: Dict[str, Any] = {"uds": {}, "suts": {}, "sds": {}, "sts_by_tc": {}, "sits_by_tc": {}}
        try:
            _direct_lc = {str(f).strip().lower() for f in _changed_set}
            _direct_list = sorted(_changed_set)
            # 키는 소문자 정규화(uds/sds와 일관) — 프론트 docContentFor가 항상 .toLowerCase()로 조회하므로
            # SUTS unit_name 원본 케이스(예 'g_DrvIn_MotorSpeed')를 그대로 두면 조회 미스→'미파싱' 오표시(reviewer W1).
            doc_content["suts"] = {str(k).strip().lower(): v for k, v in _suts_content.items() if str(k).strip().lower() in _direct_lc}
            if _lk and getattr(_lk, "uds", ""):
                doc_content["uds"] = _load_uds_fn_content(_lk.uds, _direct_list, warn_sink=warnings)
            if _lk and getattr(_lk, "sds", ""):
                doc_content["sds"] = _load_sds_fn_desc(_lk.sds, _direct_list, warn_sink=warnings)
            # STS: 전용 파서 부재 → 표준 파서 best-effort(미매칭 시 정직 '미파싱').
            if _lk and getattr(_lk, "sts", ""):
                doc_content["sts_by_tc"] = _load_testspec_by_tc(_lk.sts, warn_sink=warnings, doc_label="STS")
            # SITS: 중간 JSON(로컬 빌드 — 입력/기대값 전체)을 우선, 없으면 원본 xlsm 폴백(cloudium — 설명/사전조건).
            if _sits_by_tc:
                doc_content["sits_by_tc"] = _sits_by_tc
            elif _lk and getattr(_lk, "sits", ""):
                doc_content["sits_by_tc"] = _load_testspec_by_tc(_lk.sits, warn_sink=warnings, doc_label="SITS")
        except Exception:  # noqa: BLE001 — 문서 내용은 best-effort 표시 데이터(분석 비차단)
            pass
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
                    # Δ 신뢰도 판정 — baseline이 '같은 빌드'면 회귀 0은 '비교 불가'(위장 방지).
                    build_revision=_build_r,
                    # 이름충돌 함수는 서로 다른 copy를 전역 max로 병합하면 gap이 은폐된다 →
                    # worst-copy(min) 노출로 안전측 처리(under-report 차단).
                    collision_names=_collision_names,
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
            "function_diffs": function_diffs,
            "file_diffs": file_diffs,
            "impact": impact_groups,
            # 간접영향 근거 — {fn: {hop, via, seed}}. 프론트/AI가 "왜 간접인지"(경유 노드·최초 변경함수)를
            # 표시. impact_groups.paths와 동일(명시 top-level 키로 조회 편의). direct 함수는 미포함.
            "impact_paths": (impact_groups.get("paths") if isinstance(impact_groups, dict) else {}) or {},
            "warnings": warnings,
            "actions": actions,
            "function_meta": function_meta,
            "regression_test_set": regression_test_set,
            "doc_content": doc_content,
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
                # A 정밀분류가 함수단위로 축소한 파일 수 / 라인변경 없어 제외한 함수 수(투명성).
                "line_classified_file_count": len(_line_classified_files),
                "narrow_removed_count": _narrow_removed_n,
                # 증거 출처 집계 — granularity 스칼라가 감추던 실상("line"인데 대부분 fatten)을 노출.
                # 함수별 상세는 function_meta[fn].evidence("line" | "file_fatten").
                "evidenced_function_count": sum(1 for _v in _fn_evidence.values() if _v == "line"),
                "fattened_function_count": sum(1 for _v in _fn_evidence.values() if _v == "file_fatten"),
            },
            # 콜그래프 탐색 절단 — indirect_2hop=[]이 '영향 없음'인지 '미계산'인지 구분(오독 방지).
            "impact_traversal": {
                "truncated": bool(_bfs_stats.get("truncated")),
                "truncated_at_hop": int(_bfs_stats.get("truncated_at_hop") or 0),
                "max_impacted_functions": int(_bfs_stats.get("max_impacted_functions") or 0),
                "max_hop": int(options.max_hop),
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
            _shared_suts_tcs = _load_suts_fn_tcs(_suts_linked, _flag_fns, warn_sink=warnings) if (_has_flag and _suts_linked) else {}
            _shared_sits_chains = _load_sits_fn_chains(_sits_linked, _flag_fns, warn_sink=warnings) if (_has_flag and _sits_linked) else {}
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
                        # ⚠ 문서 1개의 자동 생성 실패가 '분석 전체 실패'가 되면 안 된다. 과거엔
                        # result["ok"]=False → impact_jobs가 fail_job으로 처리 → 이미 계산·디스크
                        # 기록까지 끝난 ISO 증거(변경함수·ASIL·커버리지·회귀·audit_path)를 통째로
                        # 폐기하고 클라이언트엔 error만 전달했다. 분석은 유효하므로 부분 실패로 표기.
                        info["status"] = "failed"
                        info["error"] = str(exc)
                        result["ok"] = False           # 하위호환: 문서 생성 실패 신호(동기 endpoint 소비)
                        result["partial_failure"] = True  # 분석 결과는 유효 — job은 완료 처리해 전달
                        warnings.append(
                            f"{target.upper()} 문서 자동 생성 실패({exc}) — 영향 분석 결과는 유효합니다"
                            "(해당 문서만 수동 생성/재시도 필요)."
                        )
                        logger.warning("impact auto action failed for %s: %s", target, exc)
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
                        # FLAG 검토 산출물 = "사람이 반드시 검토해야 한다"는 ISO 증거. 실패를 debug
                        # 로그로 삼키면 검토 대상이 통째로 사라지고 아무도 모른다 → 경고로 표면화.
                        logger.warning("review artifact write failed for %s: %s", target, _art_exc)
                        warnings.append(
                            f"{target.upper()} 검토 산출물 저장 실패 — 검토 필요 증거가 남지 않았습니다({_art_exc})."
                        )
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
            "doc_content": doc_content,
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
                "line_classified_file_count": len(_line_classified_files),
                "narrow_removed_count": _narrow_removed_n,
                # ISO 26262 추적성 — 정밀분류로 영향집합에서 제외한 함수 전체 목록(감사 레코드 durable).
                # 안전 엔지니어가 "무엇을 왜 뺐는지"를 이 레코드에서 검증할 수 있게 한다(silent drop 금지).
                "narrow_removed_functions": list(_narrow_removed_list),
                # 증거 출처 집계 — granularity 스칼라가 감추던 실상("line"인데 대부분 fatten)을 노출.
                "evidenced_function_count": sum(1 for _v in _fn_evidence.values() if _v == "line"),
                "fattened_function_count": sum(1 for _v in _fn_evidence.values() if _v == "file_fatten"),
            },
            # 콜그래프 탐색 절단 — indirect_2hop=[]이 '영향 없음'인지 '미계산'인지 구분(오독 방지).
            "impact_traversal": {
                "truncated": bool(_bfs_stats.get("truncated")),
                "truncated_at_hop": int(_bfs_stats.get("truncated_at_hop") or 0),
                "max_impacted_functions": int(_bfs_stats.get("max_impacted_functions") or 0),
                "max_hop": int(options.max_hop),
            },
        }
        # 감사기록/변경이력은 best-effort — payload가 cloudium U:\\(SMB) 접근 거부 등으로
        # 실패해도 이미 완성된 영향분석 result 반환을 막지 않는다(핵심 결과 보존).
        try:
            audit_path = write_impact_audit(audit_payload)
            result["audit_path"] = str(audit_path)
        except Exception as _audit_exc:  # noqa: BLE001
            # ⚠ ISO 26262 감사 레코드는 "무엇을 왜 분석/제외했는지"를 검증할 유일한 durable 증거다.
            # 저장 실패를 로그로만 남기면 UI는 완전한 성공 분석을 보여주고 **감사 기록은 존재하지
            # 않는다**(감사 시점까지 아무도 모름). 결과에 명시하고 경고로 표면화한다.
            logger.warning("impact audit write failed (best-effort): %s", _audit_exc)
            audit_path = None
            result["audit_write_failed"] = True
            warnings.append(
                f"감사 기록 저장 실패 — ISO 26262 추적성 레코드가 남지 않았습니다({_audit_exc}). "
                "reports/ 디스크 용량·권한을 확인하고 재실행하십시오."
            )
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
            result["change_log_write_failed"] = True
            warnings.append(
                f"변경 이력 저장 실패 — 이 실행의 변경 내역(문서별 delta)이 기록되지 않았습니다({_cl_exc})."
            )
        if callable(on_progress):
            on_progress("done", "완료되었습니다.", {"targets": len(actions)})
        return result
    finally:
        release_run_lock(trigger.scm_id)  # 명시적 키 — tid 재사용으로 남의 락을 푸는 사고 방지
