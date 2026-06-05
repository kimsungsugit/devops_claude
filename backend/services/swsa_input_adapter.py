"""SwSA 입력 어댑터 — 로그 폴더 자동 발견 + 파싱 + 다중 모듈 병합.

웹에서 사용자가 **로그 폴더 경로만** 제공하면 하위의 정적분석 산출물을 자동
발견해 파싱한다. 폴더 구조 (실측)::

    01.Log/PV/<TOOL>/<MODULE_날짜_버전>/<files>
      QAC/APP_260527_v0.05.37/results_data.xml, *_HMR_*.html, *_RCR_*.html
      QAC/BOOT_260527_v1.16/results_data.xml, *_HMR_*.html
      PMD/APP_260323/*_PMD_Report_*.txt

여러 모듈(APP/BOOT)이 있으면 프로젝트 rollup 으로 **병합**(위반/메트릭/중복 합산).
파일 read 는 ``file_resolver`` (local 또는 cloudium worker) 경유 — 본 모듈은
resolver 추상화만 의존하므로 동작 모드 무관.

ISO 26262: 발견 실패/파싱 실패는 warnings 누적 (silent skip 차단).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.services.swsa_pmd_parser import DuplicationBlock, PmdResult, parse_pmd_cpd
from backend.services.swsa_qac_xml_parser import (
    QacCategory,
    QacLeafRule,
    QacRuleGroup,
    QacXmlResult,
    parse_qac_results_xml,
)
from backend.services.swsa_st201_binner import (
    MetricResult,
    St201Result,
    parse_st201_from_hmr,
)

__all__ = [
    "SwsaLogSet",
    "SwsaInputData",
    "discover_swsa_logs",
    "collect_swsa_inputs",
    "merge_qac_results",
    "merge_st201_results",
    "merge_pmd_results",
]


def _basename(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").split("/")[-1]


@dataclass
class SwsaLogSet:
    """발견된 로그 파일 경로 (타입별)."""

    qac_xml: List[str] = field(default_factory=list)
    qac_hmr: List[str] = field(default_factory=list)
    pmd_txt: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.qac_xml) + len(self.qac_hmr) + len(self.pmd_txt)


@dataclass
class SwsaInputData:
    """파싱·병합된 입력 (aggregator 입력)."""

    qac_xml: Optional[QacXmlResult] = None
    st201: Optional[St201Result] = None
    pmd: Optional[PmdResult] = None
    log_set: SwsaLogSet = field(default_factory=SwsaLogSet)
    modules: List[str] = field(default_factory=list)  # 발견된 모듈 폴더명
    warnings: List[str] = field(default_factory=list)


# ─────────────────────────── 발견 ───────────────────────────
def discover_swsa_logs(resolver: Any, log_folder: str) -> SwsaLogSet:
    """로그 폴더 하위를 재귀 스캔해 QAC xml/HMR + PMD txt 발견.

    cloudium resolver 의 list_dir 은 파일만 반환(디렉토리 X). recursive=True 로
    전체 파일 경로를 받아 basename 패턴으로 분류한다.
    """
    log_set = SwsaLogSet()
    try:
        entries = resolver.list_dir(log_folder, pattern="*", recursive=True)
    except Exception as exc:  # noqa: BLE001
        log_set.warnings.append(f"로그 폴더 스캔 실패: {type(exc).__name__}: {exc}")
        return log_set

    for path in entries:
        name = _basename(path).lower()
        if name == "results_data.xml":
            log_set.qac_xml.append(path)
        elif "hmr" in name and name.endswith((".html", ".htm")):
            log_set.qac_hmr.append(path)
        elif "pmd" in name and name.endswith(".txt"):
            log_set.pmd_txt.append(path)

    if log_set.total == 0:
        log_set.warnings.append(
            f"로그 폴더에서 QAC/PMD 산출물 미발견: {log_folder} "
            "(results_data.xml / *HMR*.html / *PMD*.txt)"
        )
    return log_set


def _module_of(path: str) -> str:
    """.../<TOOL>/<MODULE_날짜_버전>/file → MODULE_날짜_버전."""
    parts = path.replace("\\", "/").rstrip("/").split("/")
    return parts[-2] if len(parts) >= 2 else ""


def _module_prefix_and_date(path: str) -> tuple[str, str]:
    """모듈 폴더명 → (prefix, date). 예: 'APP_260527_v0.05.37' → ('APP', '260527')."""
    folder = _module_of(path)
    toks = folder.split("_")
    prefix = toks[0] if toks else folder
    date = ""
    for t in toks[1:]:
        if t.isdigit() and len(t) >= 6:
            date = t
            break
    return prefix, date


def _select_latest_per_module(paths: List[str], kind: str, warnings: List[str]) -> List[str]:
    """동일 모듈(prefix)의 여러 분석 날짜 중 **최신만** 선택 (중복 합산 차단).

    구조 ``<TOOL>/<MODULE_날짜_버전>/file`` 에서 같은 MODULE(APP/BOOT)이 여러 날짜
    폴더에 존재하면(예: APP_260326 + APP_260527) 합산 시 메트릭/위반이 N배가 된다.
    prefix별 최신 date 만 유지하고 제외 항목은 warnings 에 기록(silent drop 차단).
    """
    by_prefix: Dict[str, tuple] = {}  # prefix -> (path, date)
    dropped: List[str] = []
    for p in paths:
        prefix, date = _module_prefix_and_date(p)
        cur = by_prefix.get(prefix)
        if cur is None:
            by_prefix[prefix] = (p, date)
        elif date > cur[1]:
            dropped.append(f"{_module_of(cur[0])}")
            by_prefix[prefix] = (p, date)
        else:
            dropped.append(f"{_module_of(p)}")
    if dropped:
        warnings.append(
            f"{kind}: 모듈별 최신 분석만 사용 — 이전 분석 제외 {sorted(set(dropped))}"
        )
    return [v[0] for v in by_prefix.values()]


# ─────────────────────────── 병합 ───────────────────────────
def merge_qac_results(results: List[QacXmlResult],
                      modules: Optional[List[str]] = None) -> Optional[QacXmlResult]:
    """여러 모듈 QacXmlResult → 프로젝트 rollup (그룹/카테고리/leaf 합산).

    modules: results 와 평행한 모듈 prefix(APP/BOOT…) 리스트. 제공 시 leaf 룰의
    per_module[prefix] 에 (total, active) 기록 → v0.11 detail(J=APP/K=BOOT) 채우기용.
    modules 미제공 시 단일 결과는 passthrough(backward compat).
    """
    pairs = [
        (r, (modules[i] if modules and i < len(modules) else ""))
        for i, r in enumerate(results)
        if r and not r.extraction_failed and r.groups
    ]
    if not pairs:
        return results[0] if results else None
    if len(pairs) == 1 and not modules:
        return pairs[0][0]

    merged = QacXmlResult(
        helix_qac_version=pairs[0][0].helix_qac_version,
        project_config=pairs[0][0].project_config,
    )
    for r, mod in pairs:
        merged.source_files_total += r.source_files_total
        merged.source_files_active += r.source_files_active
        merged.parse_warnings.extend(r.parse_warnings)
        for name, grp in r.groups.items():
            mg = merged.groups.get(name)
            if mg is None:
                mg = QacRuleGroup(name=name)
                merged.groups[name] = mg
            mg.total += grp.total
            mg.active += grp.active
            for cname, cat in grp.categories.items():
                mc = mg.categories.get(cname)
                if mc is None:
                    mc = QacCategory(name=cname)
                    mg.categories[cname] = mc
                mc.total += cat.total
                mc.active += cat.active
            # leaf 룰: id 별 합산 + 모듈별 기록
            by_id = {lr.rule_id: lr for lr in mg.leaf_rules}
            for lr in grp.leaf_rules:
                ex = by_id.get(lr.rule_id)
                if ex is None:
                    ex = QacLeafRule(rule_id=lr.rule_id, description=lr.description,
                                     severity=lr.severity)
                    mg.leaf_rules.append(ex)
                    by_id[lr.rule_id] = ex
                ex.total += lr.total
                ex.active += lr.active
                if mod:
                    pt, pa = ex.per_module.get(mod, (0, 0))
                    ex.per_module[mod] = (pt + lr.total, pa + lr.active)
    return merged


def merge_st201_results(results: List[St201Result]) -> Optional[St201Result]:
    """여러 HMR St201Result → 함수/밴드 합산."""
    valid = [r for r in results if r and r.metrics]
    if not valid:
        return results[0] if results else None
    if len(valid) == 1:
        return valid[0]

    merged = St201Result(helix_version=valid[0].helix_version)
    for r in valid:
        merged.total_functions += r.total_functions
        merged.parse_warnings.extend(r.parse_warnings)
        # 템플릿 주도 재binning 용 raw 함수값 병합 (모듈 간 concat)
        for code, vals in r.function_values.items():
            merged.function_values.setdefault(code, []).extend(vals)
        for st_id, mr in r.metrics.items():
            mm = merged.metrics.get(st_id)
            if mm is None:
                mm = MetricResult(
                    st_id=mr.st_id, metric_code=mr.metric_code, name=mr.name,
                    bands=[type(b)(label=b.label, verdict=b.verdict, count=0) for b in mr.bands],
                )
                merged.metrics[st_id] = mm
            mm.total_functions += mr.total_functions
            mm.fail_count += mr.fail_count
            mm.conditional_count += mr.conditional_count
            mm.unbinned_count += mr.unbinned_count
            mm.max_value = max(mm.max_value, mr.max_value)
            for i, b in enumerate(mr.bands):
                if i < len(mm.bands):
                    mm.bands[i].count += b.count
    return merged


def merge_pmd_results(results: List[PmdResult]) -> Optional[PmdResult]:
    """여러 PMD PmdResult → 중복 블록 합집합."""
    valid = [r for r in results if r and r.blocks]
    if not valid:
        return results[0] if results else None
    if len(valid) == 1:
        return valid[0]
    merged = PmdResult()
    seen: set = set()
    for r in valid:
        for b in r.blocks:
            key = (b.lines, b.tokens, tuple(b.files))
            if key in seen:
                continue
            seen.add(key)
            merged.blocks.append(DuplicationBlock(
                lines=b.lines, tokens=b.tokens, files=list(b.files),
                start_lines=list(b.start_lines),
            ))
    return merged


# ─────────────────────── 발견 + 파싱 + 병합 ───────────────────────
def collect_swsa_inputs(resolver: Any, log_folder: str) -> SwsaInputData:
    """로그 폴더 → 발견 → resolver read → 파싱 → 모듈 병합."""
    log_set = discover_swsa_logs(resolver, log_folder)
    # 모듈별 최신 분석 날짜만 선택 (날짜 중복 합산 차단 — APP_260326+APP_260527 등)
    log_set.qac_xml = _select_latest_per_module(log_set.qac_xml, "QAC xml", log_set.warnings)
    log_set.qac_hmr = _select_latest_per_module(log_set.qac_hmr, "QAC HMR", log_set.warnings)
    log_set.pmd_txt = _select_latest_per_module(log_set.pmd_txt, "PMD", log_set.warnings)
    data = SwsaInputData(log_set=log_set)
    data.warnings.extend(log_set.warnings)

    def _read(path: str) -> Optional[bytes]:
        try:
            return resolver.read_bytes(path)
        except Exception as exc:  # noqa: BLE001
            data.warnings.append(f"read 실패 {_basename(path)}: {type(exc).__name__}: {exc}")
            return None

    # QAC xml (ST101/ST1101)
    qac_results = []
    qac_modules = []  # results 와 평행한 prefix(APP/BOOT) — per_module 채우기용
    for p in log_set.qac_xml:
        b = _read(p)
        if b is not None:
            qac_results.append(parse_qac_results_xml(b))
            data.modules.append(_module_of(p))
            qac_modules.append(_module_prefix_and_date(p)[0])
    data.qac_xml = merge_qac_results(qac_results, qac_modules) if qac_results else None

    # HMR (ST201)
    st_results = []
    for p in log_set.qac_hmr:
        b = _read(p)
        if b is not None:
            r = parse_st201_from_hmr(b)
            r.module = _module_of(p)
            if r.metrics:  # 파싱 성공만
                st_results.append(r)
            else:
                data.warnings.extend(r.parse_warnings)
    data.st201 = merge_st201_results(st_results) if st_results else None

    # PMD (ST206)
    pmd_results = []
    for p in log_set.pmd_txt:
        b = _read(p)
        if b is not None:
            pmd_results.append(parse_pmd_cpd(b))
    data.pmd = merge_pmd_results(pmd_results) if pmd_results else None

    # 모듈 중복 제거
    data.modules = sorted(set(m for m in data.modules if m))
    return data
