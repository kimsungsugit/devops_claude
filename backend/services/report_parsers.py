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
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4", "-q"])
    from bs4 import BeautifulSoup

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional dependency
    pd = None  # type: ignore

# parse_html_report 테이블 스캔 상한 — RCR(Helix) 13테이블을 여유 있게 포괄(과거 10은 취약).
_MAX_HTML_TABLES = 40


def read_text_safe(path: Path, max_bytes: int = 10 * 1024 * 1024) -> str:
    """Read text file with size limit, supporting large files up to 10MB default."""
    if not path.exists():
        return ""
    size = path.stat().st_size
    if size > max_bytes:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(max_bytes)
    return path.read_text(encoding='utf-8', errors='ignore')


def retry_parse(max_retries: int = 2):
    """Decorator that retries parsing on failure."""
    def decorator(func):
        from functools import wraps
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
            return {"error": str(last_error)}
        return wrapper
    return decorator


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
    raw = read_text_safe(path)
    if not raw:
        summary["error"] = "read_failed"
        return summary
    if not BeautifulSoup:
        summary["error"] = "bs4_missing"
        return summary
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.string if soup.title else ""
    summary["title"] = _clean_text(title) or None
    headings = []
    for node in soup.find_all(["h1", "h2"], limit=20):
        txt = _clean_text(node.get_text(" ", strip=True))
        if txt:
            headings.append(txt)
    summary["headings"] = headings
    tables: List[Dict[str, str]] = []
    # 테이블 스캔 상한: RCR(Helix)은 13개 테이블(summary는 table#0)이라 과거 [:10]은 무해했으나
    # 레이아웃 변동 시 summary 테이블을 놓칠 수 있어 상향. 행 캡(아래 50)이 비용을 이미 제한하고,
    # extract_table_metrics는 첫 매치 우선이라 summary(선두) 값을 뒤 테이블이 덮지 않는다(무회귀).
    for table in soup.find_all("table")[:_MAX_HTML_TABLES]:
        rows: Dict[str, str] = {}
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) >= 2:
                key = _clean_text(cells[0])
                val = _clean_text(cells[1])
                if key and key not in rows:
                    rows[key] = val
            if len(rows) >= 50:
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


def _first_present(d: Dict[str, Any], *keys: str) -> Optional[Any]:
    """d에서 keys 순서로 첫 non-None 값을 반환(없으면 None).

    PRQA/Helix-QAC처럼 같은 지표를 서로 다른 라벨로 쓰는 리포트에서, 포맷별 라벨을
    순서대로 시도해 값을 회수하는 데 쓴다(첫 매치 우선).
    """
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def resolve_code_metrics(
    analysis_summary: Any,
    *,
    prqa_metrics: Optional[Dict[str, Any]] = None,
    hmr_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """analysis_summary에서 code_metrics를 해석 — lizard(complexity.csv) 우선, 없으면 QAC 폴백.

    상세탭(build_report_summary)과 대시보드(aggregate_stats)가 **동일 결과**를 쓰도록 단일 출처.
    QAC LOC은 헤더 포함이라 lizard NLOC과 값·의미가 달라(값도 큼) `source='qac'`로 명시한다.

    - `prqa_metrics`/`hmr_stats`가 주어지면(build_report_summary의 live RCR 파싱값) 그것을 우선 사용,
      아니면(aggregate) `analysis_summary["prqa"]["rcr"]["summary"]`·`["hmr"]["stats"]`(캐시)에서 해석.
    - None/비-dict는 방어(`dict(None)` 크래시 차단).
    """
    _as = analysis_summary if isinstance(analysis_summary, dict) else {}
    _cm_raw = _as.get("code_metrics")
    code_metrics = dict(_cm_raw) if isinstance(_cm_raw, dict) else {}
    _cm_absent = all(code_metrics.get(k) is None for k in ("code_files", "functions", "nloc"))
    if not _cm_absent:
        if "source" not in code_metrics:
            code_metrics["source"] = "lizard"
        return code_metrics

    # QAC 폴백 소스: live 파싱값 우선, 없으면 캐시된 analysis_summary.prqa에서.
    _prqa_raw = _as.get("prqa")
    _prqa: Dict[str, Any] = _prqa_raw if isinstance(_prqa_raw, dict) else {}
    pm = prqa_metrics
    if pm is None:
        _rcr_raw = _prqa.get("rcr")
        _rcr = _rcr_raw if isinstance(_rcr_raw, dict) else {}
        pm = _rcr.get("summary")
    pm = pm if isinstance(pm, dict) else {}
    hs = hmr_stats
    if hs is None:
        _hmr_raw = _prqa.get("hmr")
        _hmr = _hmr_raw if isinstance(_hmr_raw, dict) else {}
        hs = _hmr.get("stats")
    hs = hs if isinstance(hs, dict) else {}

    _files = _parse_number(_first_present(pm, "Number of Files", "Number of Files (including CMA)"))
    _loc = _parse_number(_first_present(
        pm, "Lines of Code (source files only)", "Lines of Code (including headers)"))
    _funcs_num = _parse_number(hs.get("functions_total"))
    if any(v is not None for v in (_files, _loc, _funcs_num)):
        return {
            "code_files": int(_files) if _files is not None else None,
            "functions": int(_funcs_num) if _funcs_num is not None else None,
            "nloc": int(_loc) if _loc is not None else None,
            "source": "qac",
        }
    return {
        "code_files": None, "functions": None, "nloc": None,
        "source": None, "reason": "no_complexity_csv_and_no_qac",
    }


def resolve_scm_vcast_metrics(payload: Any) -> Optional[Dict[str, Any]]:
    """SCM(cloudium) VectorCAST 로드 payload(비동기 잡 result.data)에서 대시보드용 경량 지표만 추출.

    상세탭 프론트(AnalysisSection.jsx effVcast 파생)와 **동일 해석**을 써서 대시보드=상세탭 일치를
    보장한다. 커버리지·TC가 모두 없으면 None을 반환(로드 이력이 무의미 — 폴백 대상 아님).

    - line_rate/branch_rate ← **UT 전용** coverage_ut.statement/branch.rate 우선(대시보드 '구문
      커버리지'는 UT 기준). coverage_ut 없으면 vcast_kind=UT일 때 top-level coverage, 그 외 합산/IT
      폴백(coverage_basis로 플래그). total=0이면 rate=None 계약 유지 → 0% 미커버 위장 금지.
    - coverage_basis: 'ut_statement'|'it_statement'|'combined_statement' — 프론트가 UT-미산출
      프로젝트만 '기준 상이' 각주로 폭로. line_rate_combined: 원 합산 구문 커버리지(투명성).
    - ut_total/it_total ← test_rows_count_ut/it(모던). 구 payload엔 이 필드가 없어 **test_rows의
      행별 source로 직접 분리**한다(_split_vcast_summary_by_source와 동일 규칙). ⚠병합 payload는
      vcast_kind가 없어 kind 추정 시 IT를 전량 UT로 오귀속하므로 test_rows 우선(실측 NE1AW 6886/616).
    - ut_passed/it_passed ← summary_ut/summary_it (없으면 결합 summary를 vcast_kind 확정 시에만 귀속).
    """
    if not isinstance(payload, dict):
        return None
    _cov_raw = payload.get("coverage")
    cov = _cov_raw if isinstance(_cov_raw, dict) else {}
    _cov_ut_raw = payload.get("coverage_ut")
    cov_ut = _cov_ut_raw if isinstance(_cov_ut_raw, dict) else {}
    kind = str(payload.get("vcast_kind") or "").upper()

    def _rate_from(d: Dict[str, Any], metric: str) -> Optional[float]:
        _cell = d.get(metric)
        cell = _cell if isinstance(_cell, dict) else {}
        r = cell.get("rate")
        # rate는 payload 계약상 total>0일 때만 숫자(total=0이면 None) → 0% 미커버 위장 방지.
        return float(r) if isinstance(r, (int, float)) else None

    # 대시보드 '구문 커버리지'는 UT 기준 — 병합 payload의 coverage_ut(UT 전용)를 우선한다. top-level
    # coverage는 UT+IT 합산이라 IT가 낮으면 희석된다(실측 KJPDS02 UT 99.5% vs 합산 70.7%).
    # 우선순위: coverage_ut.statement → (단일 UT 폴더면) top-level coverage → 그 외 합산/IT 폴백(플래그).
    _ut_stmt = _rate_from(cov_ut, "statement")
    if _ut_stmt is not None:
        line_rate = _ut_stmt
        branch_rate = _rate_from(cov_ut, "branch")
        coverage_basis = "ut_statement"
    elif kind == "UT":
        # 단일 UT 폴더: top-level coverage 자체가 UT다(coverage_ut 미분리).
        line_rate = _rate_from(cov, "statement")
        branch_rate = _rate_from(cov, "branch")
        coverage_basis = "ut_statement"
    else:
        # UT 전용 데이터 없음(IT-only 폴더 또는 legacy 병합 coverage_ut 공백) → 합산/IT로 폴백.
        # 대시보드가 이 프로젝트만 '기준 상이' 각주로 폭로한다(침묵 혼재 방지).
        line_rate = _rate_from(cov, "statement")
        branch_rate = _rate_from(cov, "branch")
        coverage_basis = "it_statement" if kind == "IT" else "combined_statement"

    # 투명성: UT로 승격돼도 원 합산 구문 커버리지를 함께 노출(프론트 각주/툴팁).
    line_rate_combined = _rate_from(cov, "statement")

    def _int(v: Any) -> Optional[int]:
        return int(v) if isinstance(v, (int, float)) else None
    ut_total = _int(payload.get("test_rows_count_ut"))
    it_total = _int(payload.get("test_rows_count_it"))
    if ut_total is None and it_total is None:
        # 구 payload(split 필드 부재): test_rows의 행별 source로 직접 분리(ground truth).
        # ⚠병합 payload는 vcast_kind가 없어 kind 추정은 IT를 전량 UT로 오귀속하므로 test_rows 우선.
        rows = payload.get("test_rows")
        if isinstance(rows, list):
            it_total = sum(
                1 for r in rows
                if isinstance(r, dict) and str(r.get("source") or "").upper() == "IT"
            )
            ut_total = len(rows) - it_total
        else:
            # test_rows조차 없는 최소 payload: 결합 카운트를 vcast_kind로 귀속(단일폴더 최후 수단).
            trc = _int(payload.get("test_rows_count"))
            if trc is not None:
                ut_total, it_total = (0, trc) if kind == "IT" else (trc, 0)
    ut_total_i = ut_total or 0
    it_total_i = it_total or 0

    if line_rate is None and not ut_total_i and not it_total_i:
        return None  # 이력은 있으나 대시보드에 쓸 커버리지·TC 없음.

    # 합격 수는 확실할 때만 귀속: summary_ut/it가 있으면 그것, 없으면 결합 summary는 단일폴더
    # (vcast_kind로 UT/IT 확정)에만 귀속. 병합(kind="")은 결합값을 한쪽에 몰면 오귀속이라 None
    # (집계 보류) — 카운트와 달리 행별 합부 재분류는 여기서 하지 않는다.
    _summary_raw = payload.get("summary")
    _summary = _summary_raw if isinstance(_summary_raw, dict) else None
    _sut_raw = payload.get("summary_ut")
    if isinstance(_sut_raw, dict):
        sut = _sut_raw
    elif kind and kind != "IT":
        sut = _summary
    else:
        sut = None
    _sit_raw = payload.get("summary_it")
    if isinstance(_sit_raw, dict):
        sit = _sit_raw
    elif kind == "IT":
        sit = _summary
    else:
        sit = None

    def _sm(s: Any, key: str) -> Optional[float]:
        s = s if isinstance(s, dict) else {}
        v = s.get(key)
        return v if isinstance(v, (int, float)) else None

    # 결합 합부(카드용) — top-level summary는 전체 test_rows _summarize_vcast_tests 출력이라
    # UT/IT 귀속 보류(병합 kind="")와 무관하게 결합 passed/failed/pass_rate는 항상 신뢰 가능하다.
    # 대시보드 '빌드 & 아티팩트 요약' VectorCAST 카드가 '통과/실패/통과율'을 여기서 읽는다
    # (집계 차트는 위 UT/IT split만 사용 — 결합값은 무시하므로 키 추가는 무회귀).
    return {
        "line_rate": line_rate,
        "line_rate_combined": line_rate_combined,
        "coverage_basis": coverage_basis,
        "branch_rate": branch_rate,
        "ut_total": ut_total_i,
        "it_total": it_total_i,
        "ut_passed": _sm(sut, "passed"),
        "it_passed": _sm(sit, "passed"),
        "passed": _sm(_summary, "passed"),
        "failed": _sm(_summary, "failed"),
        "skipped": _sm(_summary, "skipped"),
        "unknown": _sm(_summary, "unknown"),
        "pass_rate": _sm(_summary, "pass_rate"),
        "total": _sm(_summary, "total"),
    }


def parse_prqa_rcr_summary(path: Path) -> Dict[str, Any]:
    data = parse_html_report(path)
    tables = data.get("tables") or []
    metrics = extract_table_metrics(
        tables,
        [
            "Number of Files",
            "Lines of Code (source files only)",
            # Helix QAC 변형 라벨 — KJPDS02_* 등 Helix 포맷 RCR은 PRQA와 라벨이 달라
            # 파일수/LOC가 누락됐다(number_of_files=0). 두 포맷을 모두 스캔한다.
            "Number of Files (including CMA)",
            "Lines of Code (including headers)",
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


def _is_worstrules_header(headers: List[str]) -> bool:
    """헤더 시그니처로 'Most Violated Rules'(WorstRules) 테이블을 식별.

    WorstRules 테이블은 행=파일, 열=실제 규칙(Rule-8.6 등)이며 합계/진단 열이 없다.
    이 시그니처로 판별하면 앵커 네이밍 차이(bare `WorstRules` vs 숫자 `WorstRules1`)에
    무관하게 잡히고, DiagsPerParents(‘Total Violations’ 열 보유)·FileStatus
    (‘Active Diagnostics’ 열 보유)는 자연히 제외된다.
    """
    if not headers or (headers[0] or "").strip().lower() != "files":
        return False
    rule_cols = [h for h in headers[1:] if (h or "").strip()]
    if not rule_cols:
        return False
    joined = " ".join(h.lower() for h in rule_cols)
    # DiagsPerParents(‘Total Violations’) / FileStatus(‘Active Diagnostics’ 등) 배제용 열 키워드.
    # 'compliance index'로 좁혀 잡음: 규칙명에 'compliance'가 우연히 포함돼도 오배제하지 않도록.
    for bad in ("total violation", "active diagnostic", "compliance index", "violated rules", "violation count"):
        if bad in joined:
            return False
    # 규칙 열은 식별자(숫자 포함: Rule-8.6, C-INT-002 …) 형태여야 함
    return any(re.search(r"\d", h) for h in rule_cols)


# RCR 표 말미의 집계 행(파일 아님) — 파일 목록/매트릭스에서 제외.
_RCR_AGGREGATE_ROWS = {"total", "totals", "grand total", "total violations"}


def _is_rcr_aggregate_row(name: str) -> bool:
    return (name or "").strip().lower() in _RCR_AGGREGATE_ROWS


def _parse_rcr_filestatus(
    table: Any, project_root: Optional[Path] = None, job_slug: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """RCR FileStatus 테이블 → 파일별 위반수(**권위 소스**).

    반환 ``(records, total_vc)``:
      - ``records``: 표 순서 ``[{file, path_raw, path, vc(float), violated_rules?, compliance_index?}]``
        (집계행 'Total' 제외). ``vc`` = Violation Count(없으면 Diagnostic Count 폴백). key=path_raw
        (title/href) or file — WorstRules 매트릭스와 **동일 키**라 파일별 조인 가능(실측 PV 13/13·HDPDM01 12/12).
      - ``total_vc``: 집계행 'Total'의 Violation Count(있으면). ``total_vc − Σ(records.vc)`` = 파일
        미귀속 위반(F1-b) — **같은 표 안의 자립 근거**(별도 요약테이블 헤드라인에 의존하지 않음).

    FileStatus 부재/헤더 불충족이면 ``([], None)`` → 호출측이 WorstRules-only로 graceful degrade.
    """
    headers, rows, meta = _parse_table_matrix(table)
    records: List[Dict[str, Any]] = []
    total_vc: Optional[int] = None
    if not headers:
        return records, total_vc

    def _idx(name: str) -> Optional[int]:
        for idx, h in enumerate(headers):
            if name.lower() in h.lower():
                return idx
        return None

    idx_file = _idx("File")
    # ⚠ 0-index falsy 방지: `or` 체인은 매치가 컬럼 0일 때 흘려보낸다 → 첫 non-None을 명시 선택.
    idx_violation = next(
        (i for i in (_idx("Violation Count"), _idx("Violations"), _idx("Diagnostic Count"))
         if i is not None),
        None,
    )
    if idx_file is None or idx_violation is None:
        return records, total_vc
    idx_vrules = _idx("Violated Rules")
    idx_compliance = _idx("Compliance")
    for row_idx, row in enumerate(rows):
        if idx_file >= len(row) or idx_violation >= len(row):
            continue
        fname = row[idx_file]
        if _is_rcr_aggregate_row(fname):
            # 집계행 'Total'의 위반수 = 표 자립 총계(파일 미귀속 위반 산출용, 첫 집계행 채택).
            if total_vc is None:
                _t = _parse_number(row[idx_violation])
                if _t is not None:
                    total_vc = int(_t)
            continue
        vc = _parse_number(row[idx_violation]) or 0
        cell_meta: Dict[str, str] = {}
        if row_idx < len(meta) and idx_file < len(meta[row_idx]):
            cell_meta = meta[row_idx][idx_file]
        path_raw = cell_meta.get("title") or cell_meta.get("href") or ""
        rec: Dict[str, Any] = {
            "file": fname,
            "path_raw": path_raw,
            "path": _normalize_prqa_path(path_raw, project_root, job_slug),
            "vc": vc,
        }
        if idx_vrules is not None and idx_vrules < len(row):
            vr = _parse_number(row[idx_vrules])
            if vr is not None:
                rec["violated_rules"] = int(vr)
        if idx_compliance is not None and idx_compliance < len(row):
            rec["compliance_index"] = _clean_text(row[idx_compliance])
        records.append(rec)
    return records, total_vc


# RCFInfo 규칙 행의 상태 값 — 이 두 값이 아닌 행(수치 가중치 등)은 규칙 행이 아니다.
_RCF_STATUS_VALUES = {"enabled", "disabled"}


def _parse_rcr_rule_descriptions(soup: Any) -> Dict[str, Dict[str, Any]]:
    """RCFInfo(Rule Configuration Status) → ``{rule_id: {title, enabled, group}}``.

    RCR의 규칙 설명은 카운트 표(WorstRules)가 아니라 RCFInfo 표의 ``<td title=…>`` 속성에만
    있다. 행 구조 = 들여쓰기용 빈 <td> 0~N개 + ``<td title="설명">규칙ID</td>`` +
    ``<td>enabled|disabled</td>`` — 셀 수는 계층 깊이에 따라 3~7개 가변이라 셀 수로 판정하지
    않는다. M3CM-1 같은 중간 노드도 WorstRules 열 키로 쓰이므로 leaf만 거르지 않고 전부 담는다.
    RCFInfo 부재(구형 리포트)는 빈 dict — 에러 아님(설명은 부가 정보).
    """
    anchor = soup.find(attrs={"name": "RCFInfo"}) or soup.find(id="RCFInfo")
    if anchor is None:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    group = ""
    for node in anchor.find_all_next(["h3", "h5", "table"]):
        if node.name == "h3":
            break  # 다음 섹션(StatCalc 등) 진입 — RCFInfo 관할 종료
        if node.name == "h5":
            group = _clean_text(node.get_text(" ", strip=True))
            continue
        for tr in node.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue
            status = _clean_text(cells[-1].get_text(" ", strip=True)).lower()
            if status not in _RCF_STATUS_VALUES:
                continue
            rule_cell = cells[-2]
            title = (rule_cell.get("title") or "").strip()
            rule_id = _clean_text(rule_cell.get_text(" ", strip=True))
            if not rule_id or not title:
                continue
            if re.fullmatch(r"[\d.]+", rule_id):
                continue  # 수치 행(가중치 등) 방어 — 규칙 ID는 문자를 포함한다
            out.setdefault(
                rule_id, {"title": title, "enabled": status == "enabled", "group": group}
            )
    return out


def parse_prqa_rcr_details(
    path: Path,
    top_n: int = 6,
    project_root: Optional[Path] = None,
    job_slug: Optional[str] = None,
    max_files: int = 60,
) -> Dict[str, Any]:
    """PRQA/Helix QAC RCR HTML → 위반 상세.

    반환:
      - ``top_rules``  : 규칙별 위반 합계 상위 top_n (WorstRules 열 합, enabled 그룹만)
      - ``top_files``  : 파일별 위반 상위 top_n (FileStatus, violated_rules/compliance_index 포함)
      - ``violations_by_file`` : **파일 × 규칙 위반 상세** — 각 파일의 total은 FileStatus
        Violation Count(권위)이고, 규칙 분해는 WorstRules(최악 규칙)에서 온다. WorstRules는 부분집합
        이라 total − Σ(WorstRules)만큼을 ``{"rule": "기타 규칙 (비상위)", "residual": True}``로 채워
        파일별 total이 top_files·헤드라인과 정합한다(함수/라인 위반은 RCR에 없어 파일×규칙이 최상세).
      - ``violations_attributed_total`` : Σ FileStatus VC. 헤드라인 Rule Violation Count이 이보다
        크면 원본 QAC RCR이 파일 미귀속 위반을 총계에 포함한 것(파서 무관) — 프론트 각주 판단용.

    WorstRules 테이블(행=파일, 열=Rule-8.6 등)을 앵커 대신 헤더 시그니처로 스캔하므로
    구형(bare `WorstRules`)·신형(숫자 `WorstRules1`+M3CM/Secure C 다중 테이블) 리포트 모두
    처리한다. (구 코드는 ``_find_table("WorstRules")``가 숫자 앵커를 놓쳐 신형 리포트의
    top_rules가 비었음 — 시그니처 스캔이 이 버그도 해소.) FileStatus 부재 리포트는
    WorstRules-only로 graceful degrade(total=WorstRules 합).
    """
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

    # ── FileStatus (권위 파일별 위반수) — violations_by_file·top_files 공유 소스 ──
    fs_node = soup.find(attrs={"name": "FileStatus"}) or soup.find(id="FileStatus")
    fs_table = fs_node.find_next("table") if fs_node else None
    fs_records, fs_total_vc = _parse_rcr_filestatus(fs_table, project_root, job_slug)

    # ── 파일 × 규칙 매트릭스 (WorstRules 시그니처 테이블 병합 — enabled 그룹만) ──
    # 한 파일이 M3CM·Secure C 등 여러 그룹 테이블에 등장할 수 있어 규칙 카운트를 합산한다.
    # ⚠ 'Diagnostics in Disabled Rule Groups' 하위 WorstRules는 비활성 규칙이라 컴플라이언스 위반이
    #   아니다 — 병합하면 헤드라인(enabled 기준)을 초과하는 over-report → 관할 h2로 제외(F3).
    per_file: Dict[str, Dict[str, Any]] = {}
    rule_totals: Dict[str, float] = {}
    for table in soup.find_all("table"):
        headers, rows, meta = _parse_table_matrix(table)
        if not _is_worstrules_header(headers):
            continue
        h2 = table.find_previous("h2")
        if h2 and "disabled" in _clean_text(h2.get_text(" ", strip=True)).lower():
            continue
        for row_idx, row in enumerate(rows):
            if not row or len(row) < 2:
                continue
            fname = (row[0] or "").strip()
            if not fname or _is_rcr_aggregate_row(fname):
                continue
            meta_cell = (
                meta[row_idx][0] if row_idx < len(meta) and meta[row_idx] else {}
            )
            path_raw = meta_cell.get("title") or meta_cell.get("href") or ""
            # 동일 basename이 다른 디렉토리에 존재할 수 있어(예: APP/config.c vs BOOT/config.c)
            # full path(title/href)를 키로 잡아 오병합을 방지한다. path 없는 pseudo-row
            # (RCMA 등 특정 파일에 귀속되지 않은 위반 버킷)는 표시명으로 키. 같은 파일이
            # M3CM·Secure C 등 여러 그룹 테이블에 등장하면 동일 키로 규칙 카운트가 합산된다.
            key = path_raw or fname
            entry = per_file.setdefault(key, {"file": fname, "path_raw": path_raw, "rules": {}})
            for col_idx in range(1, len(headers)):
                if col_idx >= len(row):
                    continue
                rule = (headers[col_idx] or "").strip()
                if not rule:
                    continue
                cnt = int(_parse_number(row[col_idx]) or 0)
                if cnt <= 0:
                    continue
                entry["rules"][rule] = entry["rules"].get(rule, 0) + cnt
                rule_totals[rule] = rule_totals.get(rule, 0) + cnt

    top_rules: List[Dict[str, Any]] = [
        {"rule": key, "count": rule_totals[key]}
        for key in sorted(rule_totals, key=lambda k: rule_totals[k], reverse=True)[:top_n]
    ]

    # ── violations_by_file: FileStatus(권위 total) 주도 재조립 + WorstRules 규칙 분해 + 잔차 ──
    # WorstRules는 '가장 많이 위반된 규칙'만 담아 그 합은 파일 총 위반수의 부분집합이다. FileStatus
    # Violation Count(권위)를 total로 삼고 WorstRules 분해와의 차이는 '기타 규칙 (비상위)' 잔차로
    # 표시 → 파일별 total이 top_files와 일치하고 Σ가 헤드라인에 수렴(FileStatus 전용 파일도 복원).
    # FileStatus 부재 리포트면 fs_records=[] → 아래 루프를 건너뛰고 WorstRules-only로 graceful degrade.
    violations_by_file: List[Dict[str, Any]] = []
    seen_keys: set = set()
    for rec in fs_records:
        vc = int(rec["vc"])
        if vc <= 0:
            continue
        key = rec["path_raw"] or rec["file"]
        seen_keys.add(key)
        wr_rules: Dict[str, int] = per_file.get(key, {}).get("rules", {})
        rule_list: List[Dict[str, Any]] = [
            {"rule": r, "count": c}
            for r, c in sorted(wr_rules.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        wr_sum = sum(wr_rules.values())
        # 정상 데이터는 wr_sum ≤ vc(WorstRules는 부분집합) → total=vc(top_files와 정합). 소스 불일치로
        # wr_sum > vc여도 total=max로 잡아 badge 합이 total을 넘는 표시(정합 위배)를 차단(W2). residual은
        # 항상 ≥ 0이라 vc > wr_sum일 때만 '기타 규칙'을 채운다.
        total = max(vc, wr_sum)
        residual = total - wr_sum
        if residual > 0:
            # WorstRules 미포함 규칙(비상위) — 파일 total을 FileStatus 권위값에 맞춘다.
            rule_list.append({"rule": "기타 규칙 (비상위)", "count": residual, "residual": True})
        violations_by_file.append(
            {
                "file": rec["file"],
                "path": rec["path"],
                "total": total,
                "rules": rule_list,
            }
        )
    # WorstRules 전용(FileStatus에 없는 파일 — RCMA류 pseudo / 키 불일치 방어): WorstRules 합을 total로.
    for key, entry in per_file.items():
        if key in seen_keys:
            continue
        rules = entry["rules"]
        total = sum(rules.values())
        if total <= 0:
            continue
        violations_by_file.append(
            {
                "file": entry["file"],
                "path": _normalize_prqa_path(entry["path_raw"], project_root, job_slug),
                "total": total,
                "rules": [
                    {"rule": r, "count": c}
                    for r, c in sorted(rules.items(), key=lambda kv: (-kv[1], kv[0]))
                ],
            }
        )
    violations_by_file.sort(key=lambda f: (-f["total"], f["file"]))
    files_truncated = len(violations_by_file) > max_files
    violations_by_file = violations_by_file[:max_files]

    # ── top_files: FileStatus 파일별 위반수 상위 top_n (violated_rules/compliance_index 포함) ──
    top_files: List[Dict[str, Any]] = []
    if fs_records:
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for rec in fs_records:
            score = rec["vc"]
            if score <= 0:
                continue  # '위반 상위 파일'은 위반 있는 파일만 — 0건 파일이 top_n을 채우지 않도록.
            item: Dict[str, Any] = {"file": rec["file"], "count": score, "path": rec["path"]}
            if "violated_rules" in rec:
                item["violated_rules"] = rec["violated_rules"]
            if "compliance_index" in rec:
                item["compliance_index"] = rec["compliance_index"]
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        top_files = [item for _score, item in scored[:top_n]]

    # F1-b: 파일에 귀속된 위반 합(=Σ FileStatus VC). 헤드라인(Rule Violation Count)이 이보다 크면
    # 원본 QAC RCR 자체가 파일 미귀속 위반을 총계에 포함한 것(파서 무관) — 프론트가 각주로 고지.
    attributed_total = (
        int(sum(int(r["vc"]) for r in fs_records if int(r["vc"]) > 0)) if fs_records else None
    )

    result: Dict[str, Any] = {
        "path": str(path),
        "top_rules": top_rules,
        "top_files": top_files,
        "violations_by_file": violations_by_file,
        "violations_attributed_total": attributed_total,
        # W1: FileStatus 집계행 'Total' 위반수(표 자립 총계). 프론트는 이 값 − 귀속합으로 미귀속 위반을
        # 산출(별도 요약테이블 헤드라인 비의존). 부재(집계행 없음) 시 프론트가 헤드라인으로 폴백.
        "filestatus_total_vc": fs_total_vc,
        # 규칙 설명(RCFInfo <td title=…>) — 룰 트렌드/워크벤치가 규칙 ID로 조인. 부재 리포트는 빈 dict.
        "rule_descriptions": _parse_rcr_rule_descriptions(soup),
    }
    if files_truncated:
        result["files_truncated_to"] = max_files
    return result


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


def parse_vectorcast_aggregate_summary(path: Path, top_n: Optional[int] = None) -> Dict[str, Any]:
    # top_n=None → 전체 모듈 유지(침묵 절단 금지). 과거 기본 6은 line_rate 낮은 6개만 남겨 프론트가
    # "6개"를 전체처럼 오도했다(실측 30→6). 프론트 표는 스크롤 컨테이너라 전체 렌더에 문제 없음.
    # 호출측이 명시적으로 상한을 줄 때만 절단(현 호출부는 미지정 → 전체).
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
        # VectorCAST의 "Lines Covered"는 gcov식 라인 커버리지가 아니라 **statement coverage**다
        # (GRAND TOTALS의 "Statements" 값과 바이트 동일 — 실측 4396/4429). 따라서 아래 line_rate/
        # module.line_rate는 사실상 구문(Statement) 커버리지이며, 프론트가 "Statement Rate"로 표기한다.
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

    # Lazy: only parse when analysis_summary is missing (first time)
    # These are used for artifacts detail in the response
    if analysis_summary:
        parsed_html = [{"path": str(root_dir / item["rel_path"]), "title": item.get("rel_path", "")} for item in html_files[:6] if item.get("rel_path")]
        parsed_xlsx = [{"path": str(root_dir / item["rel_path"]), "sheets": [], "rows": 0} for item in xlsx_files[:3] if item.get("rel_path")]
        parsed_json = [{"path": str(root_dir / item["rel_path"]), "keys": []} for item in json_files[:5] if item.get("rel_path")]
    else:
        parsed_html = [parse_html_report(root_dir / item["rel_path"]) for item in html_files[:6] if item.get("rel_path")]
        parsed_xlsx = [parse_xlsx_report(root_dir / item["rel_path"]) for item in xlsx_files[:3] if item.get("rel_path")]
        parsed_json = [parse_json_report(root_dir / item["rel_path"]) for item in json_files[:5] if item.get("rel_path")]

    report_types: Dict[str, int] = {}
    for item in html_files + xlsx_files + json_files:
        rel = item.get("rel_path")
        if not rel:
            continue
        kind = _classify_report_type(rel)
        report_types[kind] = report_types.get(kind, 0) + 1

    build_info = _extract_build_info(analysis_summary, status)
    scan_kpis = _extract_scan_kpis(jenkins_scan)
    top_scan_files = _top_scan_files(jenkins_scan)

    # RCR HTML 후보를 report_dir 스캔 + 빌드 루트(부모)에서 모아 위치 무관 최신(mtime) 선택.
    # 일부 Jenkins 잡(KJPDS02_*)은 RCR을 report/ 하위가 아니라 빌드 루트에 둔다 → report_dir만
    # 스캔하면 RCR을 놓쳐 top_rules/top_files/violations_by_file이 전부 비고 rule_violation_count만
    # analysis_summary.json 폴백으로 남아 심층 QAC UI가 표시되지 않았다. mtime 선택은 파일명
    # 타임스탬프(DDMMYYYY, 사전순≠시간순)나 report/의 stale RCR에 오도되지 않는다.
    _rcr_cands = [root_dir / item["rel_path"] for item in html_files if "_RCR_" in item.get("rel_path", "")]
    _rcr_parent = root_dir.parent
    if _rcr_parent != root_dir:
        _rcr_cands += list(_rcr_parent.glob("*_RCR_*.html"))
    prqa_rcr_path = max(_rcr_cands, key=lambda c: c.stat().st_mtime) if _rcr_cands else None
    job_slug = _job_slug_from_dir(root_dir)
    prqa_rcr = parse_prqa_rcr_summary(prqa_rcr_path) if prqa_rcr_path else {}
    prqa_rcr_details = parse_prqa_rcr_details(
        prqa_rcr_path,
        project_root=project_root,
        job_slug=job_slug,
    ) if prqa_rcr_path else {}
    prqa_metrics = prqa_rcr.get("metrics", {}) if isinstance(prqa_rcr, dict) else {}
    # Fallback: use analysis_summary.json prqa data when HTML parsing found nothing
    if not prqa_metrics and isinstance(analysis_summary, dict):
        as_prqa = analysis_summary.get("prqa", {})
        if isinstance(as_prqa, dict):
            rcr_summary = as_prqa.get("rcr", {}).get("summary", {}) if isinstance(as_prqa.get("rcr"), dict) else {}
            if rcr_summary:
                prqa_metrics = rcr_summary
    prqa_hmr_path = next((root_dir / item["rel_path"] for item in xlsx_files if "_HMR_" in item.get("rel_path", "")), None)
    prqa_hmr = parse_xlsx_report(prqa_hmr_path) if prqa_hmr_path else {}
    # Fallback HMR stats from analysis_summary
    as_hmr_stats = {}
    if isinstance(analysis_summary, dict):
        as_prqa = analysis_summary.get("prqa", {})
        if isinstance(as_prqa, dict) and isinstance(as_prqa.get("hmr"), dict):
            as_hmr_stats = as_prqa["hmr"].get("stats", {})

    vcast_metrics_path = next((root_dir / item["rel_path"] for item in html_files if "metrics_report" in item.get("rel_path", "").lower()), None)
    vcast_metrics = parse_vectorcast_metrics_summary(vcast_metrics_path) if vcast_metrics_path else {}
    vcast_ut_aggregate = next((root_dir / item["rel_path"] for item in html_files if "aggregate_report" in item.get("rel_path", "").lower() and "_UT_" in item.get("rel_path", "")), None)
    vcast_it_aggregate = next((root_dir / item["rel_path"] for item in html_files if "aggregate_report" in item.get("rel_path", "").lower() and "_IT_" in item.get("rel_path", "")), None)
    vcast_ut_summary = parse_vectorcast_aggregate_summary(vcast_ut_aggregate) if vcast_ut_aggregate else {}
    vcast_it_summary = parse_vectorcast_aggregate_summary(vcast_it_aggregate) if vcast_it_aggregate else {}

    safe_coverage = coverage if isinstance(coverage, dict) else {}
    safe_tests = tests if isinstance(tests, dict) else {}
    # code_metrics from analysis_summary — 없으면(lizard/VectorCAST complexity.csv 부재) QAC 폴백.
    # 대시보드(aggregate_stats)와 동일 해석을 쓰도록 resolve_code_metrics 단일 출처. live RCR 파싱값
    # (prqa_metrics)·HMR stats를 넘겨 기존 동작 그대로 유지. source/reason으로 침묵 제거(프론트 라벨).
    code_metrics = resolve_code_metrics(
        analysis_summary, prqa_metrics=prqa_metrics, hmr_stats=as_hmr_stats)
    # A3: PRQA RCR 파싱 성공/실패 표식(analysis_summary 원본) — 부재 카드가 사유를 설명하도록 전파.
    _as_prqa = analysis_summary.get("prqa", {}) if isinstance(analysis_summary, dict) else {}
    if not isinstance(_as_prqa, dict):
        _as_prqa = {}
    _as_rcr_raw = _as_prqa.get("rcr")
    _as_rcr: Dict[str, Any] = _as_rcr_raw if isinstance(_as_rcr_raw, dict) else {}

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
                "violations_by_file": prqa_rcr_details.get("violations_by_file") if isinstance(prqa_rcr_details, dict) else [],
                "violations_files_truncated_to": prqa_rcr_details.get("files_truncated_to") if isinstance(prqa_rcr_details, dict) else None,
                # 파일 귀속 위반 합(Σ FileStatus VC) + 표 자립 총계(집계행) — 둘의 차 = 미귀속 위반 각주.
                "violations_attributed_total": prqa_rcr_details.get("violations_attributed_total") if isinstance(prqa_rcr_details, dict) else None,
                "filestatus_total_vc": prqa_rcr_details.get("filestatus_total_vc") if isinstance(prqa_rcr_details, dict) else None,
                "hmr_stats": as_hmr_stats,
                # 부재 시 사유 구분용(파일 없음 vs 파싱 실패) — 프론트 empty-state가 설명에 사용.
                "rcr_ok": _as_rcr.get("ok"),
                "rcr_reason": _as_rcr.get("reason"),
            },
            "code_metrics": code_metrics,
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
                # 합부 요약/실패 목록 — 빌드 산출물 경로도 SCM 경로와 동일하게 통과/실패 카드·실패
                # testcase 표를 표면화하도록(프론트 effVcast=buildVcast 경로 대칭화).
                "summary": vectorcast_rag.get("summary") if isinstance(vectorcast_rag, dict) else None,
                "failures": vectorcast_rag.get("failures", []) if isinstance(vectorcast_rag, dict) else [],
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

    # Inject test quality gates evaluation
    summary["quality_gates"] = None  # default so key always exists
    try:
        from backend.services.test_summary_service import evaluate_quality_gates
        from config import TEST_QUALITY_GATES
        _tests_kpi = summary.get("kpis", {}).get("tests", {})
        _total = _tests_kpi.get("total", 0) or 0
        _enabled = _tests_kpi.get("enabled", _total) or _total
        _ok = _tests_kpi.get("ok", 0) or 0
        _pass_rate = (_ok / _enabled) if _enabled > 0 else 0
        gate_input = {
            "pass_rate": _pass_rate,
            "coverage_line": summary.get("kpis", {}).get("coverage", {}).get("line_rate", 0),
            "coverage_branch": summary.get("kpis", {}).get("coverage", {}).get("branch_rate", 0),
            "new_failures": 0,
        }
        summary["quality_gates"] = evaluate_quality_gates(gate_input, TEST_QUALITY_GATES)
    except Exception:
        pass

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
