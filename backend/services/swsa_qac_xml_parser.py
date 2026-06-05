"""SwSA QAC ``results_data.xml`` 파서 (Helix QAC machine-readable export).

SwSA(Software Static Analysis Report) ST101(코딩 가이드라인 위반 = MISRA C:2012)
및 ST1101(시큐어 코딩 = HKMC Secure Coding)의 **1차 데이터 소스**.

Helix QAC ``results_data.xml`` 구조 (실측, Helix QAC 2025.1)::

    <AnalysisData helix_qac_version=... projectpath=... projectconfig=...>
      <dataroot type="project">              # ← 본 파서가 사용 (집계 view)
        <tree type="files">  ...Folder(파일 집계) + RuleGroup(rollup)
        <tree type="rules">                  # ← 권위 소스 (by-rule 계층)
          <RuleGroup name="M3CM" total active>          # 그룹 rollup
            <Rule id="M3CM-1" text="MISRA Mandatory">   # 카테고리 버킷
              <Rule id="..." text="...">                # (중간 분류)
                <Rule id="8.1" text="규칙 설명">          # leaf 룰 (Message 보유)
                  <Message guid total active severity text/>
        <tree type="levels"> ...
      </dataroot>
      <dataroot type="per-file"> ...File...   # ← 무시 (중복, 2× 집계 유발)
    </AnalysisData>

``total`` = 전체 검출, ``active`` = 제외(exclusion) 후 유효 위반.
``dataroot[type='project']`` 만 사용해 per-file 중복(정확히 2×)을 차단한다.

카테고리(Mandatory/Required, 또는 시큐어코딩 High/Middle/Low)는 그룹 직속 Rule 의
``text`` 로 직접 제공된다 — 템플릿 분류표 불필요. leaf 룰(Message 보유 Rule)이
개별 위반 룰이며 distinct 개수 / 상세표의 소스다.

ISO 26262: SwSA evidence 'auto-generated draft' (ASIL A 도구). reviewer 검토 의무.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

__all__ = [
    "QacLeafRule",
    "QacCategory",
    "QacRuleGroup",
    "QacXmlResult",
    "parse_qac_results_xml",
    "GROUP_MISRA",
    "GROUP_SECURE",
    "MISRA_MANDATORY",
    "MISRA_REQUIRED",
]

GROUP_MISRA = "M3CM"      # MISRA C:2012 — ST101
GROUP_SECURE = "HKCCM"    # HKMC Secure Coding — ST1101
MISRA_MANDATORY = "MISRA Mandatory"
MISRA_REQUIRED = "MISRA Required"


def _to_int(value: Optional[str]) -> int:
    try:
        return int(value) if value not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


@dataclass
class QacLeafRule:
    """개별 위반 룰 (Message 를 보유한 leaf Rule)."""

    rule_id: str               # 예: '8.1'(MISRA) 또는 'C-INT-002'(시큐어)
    description: str = ""       # Rule @text (룰 설명)
    severity: str = ""          # 소속 카테고리 text (Mandatory/Required, High/Middle/Low)
    total: int = 0
    active: int = 0
    # v0.11 detail(J=APP/K=BOOT) 채우기용 — 모듈 prefix → (total, active). 단일 모듈
    # 파싱 시 비어 있고, input_adapter.merge_qac_results 가 모듈 라벨로 채운다.
    per_module: Dict[str, tuple] = field(default_factory=dict)

    def active_for(self, module: str) -> int:
        pm = self.per_module.get(module)
        return pm[1] if pm else 0

    def excluded_for(self, module: str) -> int:
        pm = self.per_module.get(module)
        return max(0, pm[0] - pm[1]) if pm else 0

    @property
    def code_prefix(self) -> str:
        """'C-INT-002' → 'INT' (시큐어코딩 카테고리). MISRA 숫자룰은 ''."""
        parts = self.rule_id.split("-")
        if len(parts) >= 3 and parts[0].upper() == "C":
            return parts[1].upper()
        return ""


@dataclass
class QacCategory:
    """그룹 직속 카테고리 버킷 (Mandatory/Required 또는 High/Middle/Low)."""

    name: str
    total: int = 0
    active: int = 0


@dataclass
class QacRuleGroup:
    """RuleGroup(name) 프로젝트 rollup + 카테고리 + leaf 룰."""

    name: str
    total: int = 0
    active: int = 0
    categories: Dict[str, QacCategory] = field(default_factory=dict)
    leaf_rules: List[QacLeafRule] = field(default_factory=list)

    @property
    def excluded(self) -> int:
        return max(0, self.total - self.active)

    def category(self, name: str) -> QacCategory:
        return self.categories.get(name, QacCategory(name=name))

    def distinct_rules(self, *, use_active: bool = True) -> int:
        """위반 1건 이상인 distinct leaf 룰 개수 (= '위반 룰 개수')."""
        return sum(1 for r in self.leaf_rules if (r.active if use_active else r.total) > 0)

    def rules_sorted(self) -> List[QacLeafRule]:
        """active 위반 내림차순 (상세표용)."""
        return sorted(self.leaf_rules, key=lambda r: (-r.active, -r.total, r.rule_id))

    def by_prefix(self, *, use_active: bool = True) -> Dict[str, int]:
        """code_prefix(INT/DCI/...) 별 위반 합계 (ST1101 카테고리 맵용)."""
        out: Dict[str, int] = {}
        for r in self.leaf_rules:
            v = r.active if use_active else r.total
            if v <= 0:
                continue
            out[r.code_prefix or "?"] = out.get(r.code_prefix or "?", 0) + v
        return out


@dataclass
class QacXmlResult:
    helix_qac_version: str = ""
    helix_qac_build: str = ""
    project_path: str = ""
    project_config: str = ""
    timestamp: str = ""
    source_files_total: int = 0
    source_files_active: int = 0
    groups: Dict[str, QacRuleGroup] = field(default_factory=dict)
    parse_warnings: List[str] = field(default_factory=list)
    # C1/C2: 구조적 추출 실패 신호. True 면 '위반 0건'이 아니라 '파싱/추출 실패' —
    # 호출자(aggregator)는 0 stamp 대신 노란 '사용자 입력 필요' 처리해야 한다.
    extraction_failed: bool = False

    def group(self, name: str) -> Optional[QacRuleGroup]:
        return self.groups.get(name)

    @property
    def misra(self) -> Optional[QacRuleGroup]:
        return self.groups.get(GROUP_MISRA)

    @property
    def secure(self) -> Optional[QacRuleGroup]:
        return self.groups.get(GROUP_SECURE)


def _load_root(source: Union[str, bytes, Path]) -> ET.Element:
    """XML 로드. 빈/손상 입력은 ValueError/ET.ParseError, 미존재 경로는 FileNotFoundError."""
    if isinstance(source, (bytes, bytearray)):
        if not bytes(source).strip():
            raise ValueError("QAC xml: 빈 입력(bytes)")
        return ET.parse(io.BytesIO(bytes(source))).getroot()
    if isinstance(source, str):
        if not source.strip():
            raise ValueError("QAC xml: 빈 문자열 입력")
        if source.lstrip().startswith("<"):
            return ET.fromstring(source)
    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(f"QAC xml not found: {source!r}")
    if p.is_dir():
        # 빈 문자열이 Path('.')→디렉토리로 빠지는 혼란 방지
        raise FileNotFoundError(f"QAC xml is a directory: {source!r}")
    return ET.parse(p).getroot()


def _collect_leaf_rules(category_el: ET.Element, severity: str) -> List[QacLeafRule]:
    """카테고리 Rule 하위에서 Message 를 직접 보유한 leaf Rule 들을 수집."""
    leaves: List[QacLeafRule] = []
    for rule_el in category_el.iter("Rule"):
        # leaf = Message 자식을 직접 보유한 Rule
        if rule_el.find("Message") is None:
            continue
        leaves.append(QacLeafRule(
            rule_id=rule_el.get("id") or "",
            description=rule_el.get("text", "") or "",
            severity=severity,
            total=_to_int(rule_el.get("total")),
            active=_to_int(rule_el.get("active")),
        ))
    return leaves


def parse_qac_results_xml(source: Union[str, bytes, Path]) -> QacXmlResult:
    """results_data.xml → QacXmlResult.

    Args:
        source: 파일 경로(str/Path), raw bytes, 또는 XML 문자열.

    Returns:
        QacXmlResult. 손상/빈 XML 은 extraction_failed=True + parse_warnings 로
        graceful 반환 (silent skip 차단). 미존재 경로만 FileNotFoundError raise.
    """
    result = QacXmlResult()
    try:
        root = _load_root(source)
    except (ET.ParseError, ValueError) as exc:
        # 손상/빈 XML 은 부분 데이터 손실 — 빌드 전체 크래시 대신 graceful 신호
        result.parse_warnings.append(f"XML 파싱 실패(손상/빈 입력 추정): {exc}")
        result.extraction_failed = True
        return result
    result.helix_qac_version = root.get("helix_qac_version", "")
    result.helix_qac_build = root.get("helix_qac_build", "")
    result.project_path = root.get("projectpath", "")
    result.project_config = root.get("projectconfig", "")
    result.timestamp = root.get("timestamp", "")

    # dataroot[type='project'] 만 사용 (per-file 중복 차단)
    project = next((d for d in root if d.tag == "dataroot" and d.get("type") == "project"), None)
    if project is None:
        # per-file dataroot 만 있는 변종: 아무 dataroot 라도 잡되 명시적 경고.
        # (per-file dataroot 는 tree 가 없어 아래에서 RuleGroup 0 → extraction_failed)
        project = next((d for d in root if d.tag == "dataroot"), None) or root
        result.parse_warnings.append(
            "dataroot[type=project] 미발견 — 대체 스캔 (중복/추출불가 위험)"
        )

    trees = {t.get("type"): t for t in project.findall("tree")}

    # 파일 집계 (tree[type='files'] 의 Folder basename='Source Files')
    files_tree = trees.get("files")
    if files_tree is not None:
        for folder in files_tree.iter("Folder"):
            if (folder.get("basename") or "").strip().lower() == "source files":
                result.source_files_total = _to_int(folder.get("total"))
                result.source_files_active = _to_int(folder.get("active"))
                break

    # by-rule 계층: tree[type='rules'] 가 권위 소스. files tree 는 보통 RuleGroup 이
    # 없으므로(Folder 만 보유) 진짜 fallback 이 아님 — 부재 시 명시적 추출실패 신호.
    # 주의: ElementTree 요소는 자식이 없으면 falsy → 반드시 `is None` 비교.
    rules_tree = trees.get("rules")
    if rules_tree is None:
        rules_tree = files_tree  # 최후 시도 (실 구조상 RuleGroup 0 가능성 높음)
    if rules_tree is None or not rules_tree.findall("RuleGroup"):
        result.parse_warnings.append(
            "tree[rules] 부재 + 대체 트리에 RuleGroup 없음 — by-rule 집계 불가 "
            "(위반 0건 아님, 추출 실패)"
        )
        result.extraction_failed = True
        return result

    for group_el in rules_tree.findall("RuleGroup"):
        name = group_el.get("name") or ""
        if not name:
            continue
        grp = QacRuleGroup(
            name=name,
            total=_to_int(group_el.get("total")),
            active=_to_int(group_el.get("active")),
        )
        # 카테고리 = 그룹 직속 Rule
        for cat_el in group_el.findall("Rule"):
            cat_name = cat_el.get("text", "") or (cat_el.get("id") or "")
            grp.categories[cat_name] = QacCategory(
                name=cat_name,
                total=_to_int(cat_el.get("total")),
                active=_to_int(cat_el.get("active")),
            )
            grp.leaf_rules.extend(_collect_leaf_rules(cat_el, cat_name))
        result.groups[name] = grp

    # 정합성 경고 (W4): 카테고리 active 합 != 그룹 active — audit 정확성 문맥상
    # 단 1건 차이도 경고 (이전 5% 관대 임계 제거). 실데이터는 정확히 일치(286=286).
    for name, grp in result.groups.items():
        cat_sum = sum(c.active for c in grp.categories.values())
        if cat_sum != grp.active:
            result.parse_warnings.append(
                f"{name}: 카테고리 active 합({cat_sum}) != 그룹 active({grp.active}) "
                f"— 분류 누락/중복 검토 필요"
            )

    if not result.groups:
        result.parse_warnings.append("RuleGroup 미발견 — results_data.xml 형식 확인 필요")
        result.extraction_failed = True

    return result
