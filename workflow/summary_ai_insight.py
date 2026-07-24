"""프로젝트 요약탭 AI 인사이트 — 결정론 코어 + Gemini enrichment(실패 시 폴백).

구조는 workflow/impact_ai_guide.py 규약을 따른다:
- 결정론 코어(build_deterministic_insight)는 LLM 없이 항상 동작한다
- enrichment는 섹션별 try/except 격리 — 실패 섹션만 ai_enriched:false + 결정론 폴백
- LLM 미설정은 정상 경로(None 반환), 코드/호출 실패는 warning으로 승격
  (폴백 뒤에 배선 버그가 숨던 impact_ai_guide 전례 방지)
- 환각 방지: LLM 출력의 규칙/파일명을 입력 집합으로 사후 필터(입력에 없는 것은 버림)

IO(캐시 파일·RCR 파싱·소스 읽기)는 라우터(backend/routers/summary_insight.py)가 담당하고
이 모듈은 주어진 입력 → 인사이트 계산만 한다(코드 발췌 reader도 주입식 — 계층 위반 회피).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 프롬프트/출력 스키마 개정 시 +1 — 라우터가 캐시 무효화 판단에 사용.
# v2: architecture 섹션 추가(Phase G) — 전 캐시 자연 무효화.
PROMPT_VERSION = 2
SECTIONS = ("rules", "mistakes", "roles", "architecture")
EXCERPT_MAX_FILES = 4
EXCERPT_MAX_BYTES_PER_FILE = 4096
EXCERPT_MAX_TOTAL_BYTES = 16384


@dataclass
class SummaryInsightInput:
    """결정론 코어 + enrichment의 입력(라우터가 조립).

    delta는 prqa_delta.compute_prqa_pair_delta 결과(+signals) 또는 None —
    None은 '계산 불가'이며 0으로 위장하지 않는다(available:false 전파).
    """
    job_slug: str = ""
    latest_build: Optional[int] = None
    baseline_build: Optional[int] = None
    headline: Dict[str, Any] = field(default_factory=dict)  # violations/compliance/coverage_line…
    top_rules: List[Dict[str, Any]] = field(default_factory=list)  # [{rule,count,files_affected}]
    delta: Optional[Dict[str, Any]] = None
    signals: List[Dict[str, Any]] = field(default_factory=list)
    complexity_offenders: List[Dict[str, Any]] = field(default_factory=list)  # [{function,vg,file}]
    vcast_failures: List[Dict[str, Any]] = field(default_factory=list)
    trace_summary: Optional[Dict[str, Any]] = None
    code_excerpts: List[Dict[str, Any]] = field(default_factory=list)  # [{path,bytes,text,truncated}]
    arch_metrics: Optional[Dict[str, Any]] = None  # summary_arch_metrics 결과(부재=None)


# ---------------------------------------------------------------------------
# 파생 헬퍼 (순수)
# ---------------------------------------------------------------------------

def top_rules_with_files(details: Dict[str, Any], top_n: int = 10) -> List[Dict[str, Any]]:
    """RCR 상세(violations_by_file)에서 규칙별 총 위반 + 영향 파일 수를 낸다.

    top_rules(파서의 top_n 절단본) 대신 전체에서 재합산 — 절단 오염 방지.
    residual('기타') 행은 규칙이 아니므로 제외.
    """
    counts: Dict[str, int] = {}
    files: Dict[str, set] = {}
    for f in details.get("violations_by_file") or []:
        fkey = str((f or {}).get("path") or (f or {}).get("file") or "")
        for r in (f or {}).get("rules") or []:
            if r.get("residual"):
                continue
            rule = str(r.get("rule") or "").strip()
            try:
                cnt = int(r.get("count") or 0)
            except (TypeError, ValueError):
                continue
            if not rule or cnt <= 0:
                continue
            counts[rule] = counts.get(rule, 0) + cnt
            files.setdefault(rule, set()).add(fkey)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return [
        {"rule": rule, "count": cnt, "files_affected": len(files.get(rule) or ())}
        for rule, cnt in ranked
    ]


def collect_code_excerpts(
    read_text: Callable[[str], str],
    candidate_paths: List[str],
    *,
    max_files: int = EXCERPT_MAX_FILES,
    max_bytes_per_file: int = EXCERPT_MAX_BYTES_PER_FILE,
    max_total_bytes: int = EXCERPT_MAX_TOTAL_BYTES,
) -> List[Dict[str, Any]]:
    """실수 패턴 진단용 실제 코드 발췌 — 캡 강제(파일 수/파일당/총량).

    read_text는 주입식(라우터가 file_resolver 기반 reader 전달) — 실패(부재/권한)는
    해당 후보 스킵(fail-soft). 발췌는 파일 head 기준(라인 위반 위치가 데이터에 없음).
    """
    out: List[Dict[str, Any]] = []
    total = 0
    seen: set = set()
    for path in candidate_paths:
        if len(out) >= max_files or total >= max_total_bytes:
            break
        p = str(path or "").strip()
        if not p or p in seen:
            continue
        seen.add(p)
        try:
            text = read_text(p)
        except Exception:  # silent-ok: 발췌는 best-effort — 후보 부재/권한 실패는 스킵(코어 동작 무관)
            continue
        if not text:
            continue
        budget = min(max_bytes_per_file, max_total_bytes - total)
        raw = text.encode("utf-8", errors="ignore")
        truncated = len(raw) > budget
        snippet = raw[:budget].decode("utf-8", errors="ignore")
        total += min(len(raw), budget)
        out.append({"path": p, "bytes": min(len(raw), budget), "text": snippet, "truncated": truncated})
    return out


def resolve_effective_model(cfg: Optional[Dict[str, Any]]) -> Optional[str]:
    """실호출 모델명 — llm_call과 동일 우선순위(cfg.model_override > env LLM_MODEL_OVERRIDE > cfg.model).

    응답 `model` 필드(감사 푸터)와 캐시 히트 판정이 cfg.model만 보면, .env 하드락이 켜진
    배포에서 표기·캐시키가 실호출 모델과 어긋난다(gemini-2.5 표기 ↔ 3.x 실호출 전례).
    """
    if not cfg:
        return None
    override = str(cfg.get("model_override") or os.environ.get("LLM_MODEL_OVERRIDE") or "").strip()
    model = override or str(cfg.get("model") or "").strip()
    return model or None


def _extract_json_payload(text: str) -> Optional[Any]:
    """LLM 응답에서 JSON을 강건 추출 — 코드펜스/서두 잡음 허용(uds_ai 규약)."""
    if not text or not isinstance(text, str):
        return None
    stripped = re.sub(r"```(?:json)?", "", text).strip()
    # 먼저 등장하는 괄호 유형을 우선 — '[ {...} ]'에서 {} 우선이면 배열 대신 내부 객체만 뽑힌다.
    pairs = sorted(
        (p for p in (("{", "}"), ("[", "]")) if stripped.find(p[0]) != -1),
        key=lambda p: stripped.find(p[0]),
    )
    for open_ch, close_ch in pairs:
        start = stripped.find(open_ch)
        end = stripped.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start:end + 1])
            except (ValueError, TypeError):
                continue
    return None


def compute_cache_key(inp: SummaryInsightInput, model: str) -> str:
    """캐시 키 = 모델 + 프롬프트버전 + 빌드쌍 + 입력 지문.

    임베딩 캐시의 교훈(키에 model 미포함 → 모델 교체 후 stale) 승계 — 모델/프롬프트/
    입력(top_rules·delta 요약)이 바뀌면 키가 바뀐다.
    """
    delta = inp.delta or {}
    fingerprint = [
        str(model or ""),
        PROMPT_VERSION,
        inp.job_slug,
        inp.latest_build,
        inp.baseline_build,
        [(r.get("rule"), r.get("count")) for r in inp.top_rules],
        (delta.get("totals") or {}),
        {k: len(v) for k, v in (delta.get("rules") or {}).items() if isinstance(v, list)},
        len(inp.code_excerpts),
    ]
    blob = json.dumps(fingerprint, ensure_ascii=False, sort_keys=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 결정론 코어
# ---------------------------------------------------------------------------

def build_deterministic_insight(inp: SummaryInsightInput) -> Dict[str, Any]:
    """LLM 없이 항상 산출되는 구조화 인사이트 — enrichment의 근거이자 폴백."""
    delta = inp.delta or {}
    rules = delta.get("rules") or {}
    delta_summary = {
        "available": bool(inp.delta),
        "new_rules": len(rules.get("new") or []),
        "resolved_rules": len(rules.get("resolved") or []),
        "increased_rules": len(rules.get("increased") or []),
        "decreased_rules": len(rules.get("decreased") or []),
        "residual_delta": rules.get("residual_delta") if inp.delta else None,
        "changed_files_with_increase": len(inp.signals),
    }
    gaps: List[Dict[str, Any]] = []
    ts = inp.trace_summary or {}
    if ts.get("has_data"):
        for kind, key in (
            ("trace_uncovered", "uncovered"),
            ("asil_test_gap", "asil_gap_count"),
            ("asil_unknown", "asil_unknown_count"),
        ):
            v = ts.get(key)
            if isinstance(v, (int, float)) and v > 0:
                gaps.append({"kind": kind, "count": int(v)})
    if inp.vcast_failures:
        gaps.append({"kind": "test_failures", "count": len(inp.vcast_failures)})
    cov = inp.headline.get("coverage_line")
    if cov is None:
        gaps.append({"kind": "coverage_unmeasured", "count": None})
    arch = inp.arch_metrics if isinstance(inp.arch_metrics, dict) else None
    return {
        "headline": dict(inp.headline),
        "top_rules": list(inp.top_rules),
        "delta_summary": delta_summary,
        "complexity_offenders": list(inp.complexity_offenders[:10]),
        "gaps": gaps,
        # 아키텍처 요약(결정론) — 부재는 available:false(침묵 생략 금지).
        "architecture": (
            {
                "available": True,
                "snapshot": arch.get("snapshot"),
                "hotspots": (arch.get("hotspots") or [])[:5],
                "coupling": arch.get("coupling"),
                "size_outliers": (arch.get("size_outliers") or [])[:5],
            }
            if arch and arch.get("available")
            else {"available": False, "reason": (arch or {}).get("reason") or "no_source_snapshot"}
        ),
    }


def _deterministic_role_guidance(det: Dict[str, Any], inp: SummaryInsightInput) -> Dict[str, List[Dict[str, Any]]]:
    """LLM 폴백용 역할별 권고 — 결정론 규칙 기반, basis는 항상 입력 수치 인용."""
    dev: List[Dict[str, Any]] = []
    tester: List[Dict[str, Any]] = []
    ds = det["delta_summary"]
    if ds["available"] and (ds["new_rules"] or ds["increased_rules"]):
        dev.append({
            "action": "이번 빌드에서 새로 생기거나 늘어난 위반 규칙을 우선 정리",
            "basis": f"신규 규칙 {ds['new_rules']}종 · 증가 규칙 {ds['increased_rules']}종",
        })
    if ds["changed_files_with_increase"]:
        top = [str(s.get("file") or "").split("/")[-1] for s in inp.signals[:3]]
        dev.append({
            "action": f"변경한 파일의 위반 증가 해소({', '.join(top)})",
            "basis": f"변경 파일 중 위반 증가 {ds['changed_files_with_increase']}개",
        })
    if det["top_rules"]:
        r0 = det["top_rules"][0]
        dev.append({
            "action": f"최다 위반 규칙 {r0['rule']} 집중 정리",
            "basis": f"{r0['rule']} 위반 {r0['count']}건 · 파일 {r0.get('files_affected', '—')}개",
        })
    for c in det["complexity_offenders"][:1]:
        dev.append({
            "action": f"고복잡도 함수 리팩토링 검토({c.get('function')})",
            "basis": f"순환복잡도 vg={c.get('vg')}",
        })
    for g in det["gaps"]:
        if g["kind"] == "test_failures":
            tester.append({"action": "실패 테스트케이스 원인 분석·재실행 우선", "basis": f"실패 TC {g['count']}건"})
        elif g["kind"] == "asil_test_gap":
            tester.append({"action": "ASIL 등급 대비 시험 수준 미달 요구 보강", "basis": f"ASIL 시험 미달 {g['count']}건"})
        elif g["kind"] == "trace_uncovered":
            tester.append({"action": "미추적 요구에 시험 매핑 추가", "basis": f"미추적 요구 {g['count']}건"})
        elif g["kind"] == "asil_unknown":
            tester.append({"action": "ASIL 미상 요구 등급 확정(QM 단정 금지)", "basis": f"ASIL 미상 {g['count']}건"})
        elif g["kind"] == "coverage_unmeasured":
            tester.append({"action": "커버리지 측정 파이프라인 연결 확인", "basis": "구문 커버리지 미측정(증거 부재)"})
    if not dev:
        dev.append({"action": "위반/복잡도 특이사항 없음 — 현 수준 유지", "basis": "delta·상위 규칙에 이상 신호 없음"})
    if not tester:
        tester.append({"action": "시험 갭 특이사항 없음 — 회귀 스위트 유지", "basis": "실패/ASIL 미달/미추적 0"})
    for i, item in enumerate(dev):
        item["priority"] = i + 1
    for i, item in enumerate(tester):
        item["priority"] = i + 1
    return {"developer": dev[:5], "tester": tester[:5]}


# ---------------------------------------------------------------------------
# LLM enrichment (섹션별 격리)
# ---------------------------------------------------------------------------

def _call_llm_json(cfg: Optional[Dict[str, Any]], system: str, user_payload: str, *, stage: str,
                   agent_call: Optional[Callable[..., Optional[str]]] = None) -> Optional[Any]:
    """공통 LLM 호출(JSON 강제) — cfg 없음/출력 파싱 실패는 None(폴백 정상 경로)."""
    if not cfg:
        return None
    if agent_call is None:
        from workflow.ai import agent_call_text as agent_call  # noqa: PLC0415 — 순환/기동비용 회피 지연 import
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_payload},
    ]
    output = agent_call(cfg, messages, role="analysis", stage=stage)
    return _extract_json_payload(output or "")


def _known_rule_set(inp: SummaryInsightInput) -> set:
    rules = {str(r.get("rule") or "") for r in inp.top_rules}
    delta_rules = (inp.delta or {}).get("rules") or {}
    for key in ("new", "resolved", "increased", "decreased"):
        rules.update(str(r.get("rule") or "") for r in delta_rules.get(key) or [])
    rules.discard("")
    return rules


def _known_file_set(inp: SummaryInsightInput) -> set:
    files = {str(e.get("path") or "") for e in inp.code_excerpts}
    for f in (inp.delta or {}).get("files") or []:
        files.add(str(f.get("path") or f.get("file") or ""))
    for s in inp.signals:
        files.add(str(s.get("file") or ""))
    files.discard("")
    return files


def enrich_rule_insight(cfg, inp: SummaryInsightInput, det: Dict[str, Any], *, agent_call=None) -> Optional[List[Dict[str, Any]]]:
    """(a) 위반 룰 해설 — 왜 위험한가/전형 원인/수정 가이드. 실패 시 None."""
    from prompts import load_prompt
    system = load_prompt("summary_rule_insight")
    payload = json.dumps({
        "project": inp.job_slug, "builds": [inp.baseline_build, inp.latest_build],
        "top_rules": det["top_rules"], "delta_rules": (inp.delta or {}).get("rules"),
    }, ensure_ascii=False)
    parsed = _call_llm_json(cfg, system, payload, stage="summary_rules", agent_call=agent_call)
    items = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return None
    known = _known_rule_set(inp)
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("rule") or "") not in known:
            continue  # 환각 규칙 차단 — 입력에 없는 규칙 번호는 버린다
        out.append({k: it.get(k) for k in ("rule", "title", "why_risky", "typical_cause", "fix_guide")})
    return out or None


def enrich_mistake_patterns(cfg, inp: SummaryInsightInput, det: Dict[str, Any], *, agent_call=None) -> Optional[List[Dict[str, Any]]]:
    """(b) 개발자 실수 패턴 — 반복 위반 + 실제 코드 발췌 기반 진단/개선안. 실패 시 None."""
    from prompts import load_prompt
    system = load_prompt("summary_mistake_patterns")
    excerpt_text = "\n\n".join(
        f"=== {e['path']} (발췌 {e['bytes']} bytes{', truncated' if e.get('truncated') else ''}) ===\n{e['text']}"
        for e in inp.code_excerpts
    ) or "(코드 발췌 없음 — 통계만으로 판단하고 confidence를 낮출 것)"
    payload = json.dumps({
        "top_rules": det["top_rules"], "delta_rules": (inp.delta or {}).get("rules"),
        "signals": inp.signals, "complexity_offenders": det["complexity_offenders"],
    }, ensure_ascii=False) + "\n\n[실제 코드 발췌]\n" + excerpt_text
    parsed = _call_llm_json(cfg, system, payload, stage="summary_mistakes", agent_call=agent_call)
    items = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return None
    known_rules = _known_rule_set(inp)
    known_files = _known_file_set(inp)
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        rules = [r for r in (it.get("rules") or []) if str(r) in known_rules]
        files = [f for f in (it.get("files") or []) if str(f) in known_files]
        if not rules and not files:
            continue  # 입력 근거가 하나도 없는 패턴은 환각으로 간주
        conf = str(it.get("confidence") or "low").lower()
        out.append({
            "pattern": it.get("pattern"), "rules": rules, "files": files,
            "diagnosis": it.get("diagnosis"), "improvement": it.get("improvement"),
            "evidence_quote": it.get("evidence_quote"),
            "confidence": conf if conf in ("high", "medium", "low") else "low",
        })
    return out or None


def _known_symbol_set(inp: SummaryInsightInput) -> set:
    """아키텍처 섹션 환각 필터 어휘 — 메트릭에 등장한 함수/파일만 허용."""
    arch = inp.arch_metrics or {}
    out: set = set()
    for key in ("fan", "hotspots", "size_outliers"):
        for r in arch.get(key) or []:
            if r.get("function"):
                out.add(str(r["function"]))
            if r.get("file"):
                out.add(str(r["file"]))
    for p in (arch.get("coupling") or {}).get("top_pairs") or []:
        out.add(str(p.get("from_file") or ""))
        out.add(str(p.get("to_file") or ""))
    for e in arch.get("excerpts") or []:
        if e.get("function"):
            out.add(str(e["function"]))
    out.discard("")
    return out


def enrich_architecture(cfg, inp: SummaryInsightInput, det: Dict[str, Any], *, agent_call=None) -> Optional[List[Dict[str, Any]]]:
    """(d) 아키텍처 조언 — 메트릭+핫스팟 발췌 기반. 메트릭 부재/실패 시 None."""
    arch = inp.arch_metrics
    if not (isinstance(arch, dict) and arch.get("available")):
        return None
    from prompts import load_prompt
    system = load_prompt("summary_architecture")
    excerpt_text = "\n\n".join(
        f"=== {e.get('function')} ({e.get('file')}{', truncated' if e.get('truncated') else ''}) ===\n{e.get('text')}"
        for e in arch.get("excerpts") or []
    ) or "(핫스팟 발췌 없음 — 수치만으로 판단하고 confidence를 낮출 것)"
    payload = json.dumps({
        "snapshot": arch.get("snapshot"),
        "fan": arch.get("fan"),
        "hotspots": arch.get("hotspots"),
        "coupling": arch.get("coupling"),
        "size_outliers": arch.get("size_outliers"),
        "asil_functions": arch.get("asil_functions"),
    }, ensure_ascii=False) + "\n\n[핫스팟 함수 본문 발췌]\n" + excerpt_text
    parsed = _call_llm_json(cfg, system, payload, stage="summary_architecture", agent_call=agent_call)
    items = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return None
    known = _known_symbol_set(inp)
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get("finding"):
            continue
        functions = [f for f in (it.get("functions") or []) if str(f) in known]
        files = [f for f in (it.get("files") or []) if str(f) in known]
        if not functions and not files:
            continue  # 메트릭에 없는 심볼만 언급 — 환각으로 간주
        topic = str(it.get("topic") or "").strip() or "refactor_candidate"
        conf = str(it.get("confidence") or "low").lower()
        out.append({
            "topic": topic if topic in ("layering", "coupling", "refactor_candidate", "hotspot") else "refactor_candidate",
            "finding": it.get("finding"),
            "suggestion": it.get("suggestion"),
            "functions": functions,
            "files": files,
            "basis": it.get("basis"),
            "confidence": conf if conf in ("high", "medium", "low") else "low",
        })
    return out or None


def enrich_role_guidance(cfg, inp: SummaryInsightInput, det: Dict[str, Any], *, agent_call=None) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """(c) 개발자/테스터 역할별 권고 — basis는 입력 수치 인용 의무. 실패 시 None."""
    from prompts import load_prompt
    system = load_prompt("summary_role_guidance")
    payload = json.dumps({
        "deterministic": det,
        "pipeline": {
            "trace": inp.trace_summary, "vcast_failures_count": len(inp.vcast_failures),
            "vcast_failures_sample": inp.vcast_failures[:5],
        },
    }, ensure_ascii=False, default=str)
    parsed = _call_llm_json(cfg, system, payload, stage="summary_roles", agent_call=agent_call)
    if not isinstance(parsed, dict):
        return None
    out: Dict[str, List[Dict[str, Any]]] = {}
    for role in ("developer", "tester"):
        items = parsed.get(role)
        if not isinstance(items, list):
            return None  # 한쪽 결손이면 전체 폴백(반쪽 권고가 더 혼란)
        cleaned = []
        for i, it in enumerate(items[:5]):
            if not isinstance(it, dict) or not it.get("action"):
                continue
            cleaned.append({
                "priority": int(it.get("priority") or (i + 1)),
                "action": str(it.get("action")),
                "basis": str(it.get("basis") or ""),
            })
        if not cleaned:
            return None
        out[role] = cleaned
    return out


# ---------------------------------------------------------------------------
# 조립
# ---------------------------------------------------------------------------

def generate_summary_insight(
    inp: SummaryInsightInput,
    *,
    sections: tuple = SECTIONS,
    use_llm: bool = True,
    llm_cfg: Optional[Dict[str, Any]] = None,
    agent_call: Optional[Callable[..., Optional[str]]] = None,
) -> Dict[str, Any]:
    """결정론 코어 + 요청 섹션 enrichment. 섹션별 실패 격리(한 섹션이 다른 섹션을 죽이지 않음).

    llm_cfg 미전달 시 impact_ai_guide._load_impact_oai_config로 해석
    ("챗이 되는 배포면 인사이트도 된다" 계약 승계). use_llm=False면 LLM 0회.
    """
    det = build_deterministic_insight(inp)
    cfg = None
    if use_llm:
        if llm_cfg is not None:
            cfg = llm_cfg
        else:
            try:
                from workflow.impact_ai_guide import _load_impact_oai_config
                cfg = _load_impact_oai_config()
            except Exception:
                logger.warning("summary insight LLM config 해석 실패 — 결정론 폴백", exc_info=True)
                cfg = None

    out_sections: Dict[str, Any] = {}
    enrichers = {
        "rules": lambda: enrich_rule_insight(cfg, inp, det, agent_call=agent_call),
        "mistakes": lambda: enrich_mistake_patterns(cfg, inp, det, agent_call=agent_call),
        "roles": lambda: enrich_role_guidance(cfg, inp, det, agent_call=agent_call),
        "architecture": lambda: enrich_architecture(cfg, inp, det, agent_call=agent_call),
    }
    for name in sections:
        if name not in enrichers:
            continue
        enriched = None
        reason = None
        if cfg is None:
            reason = "llm_unavailable"
        else:
            try:
                enriched = enrichers[name]()
                if enriched is None:
                    reason = "llm_empty_or_invalid"
            except Exception:
                # 코드/호출 실패는 warning(배선 버그가 폴백 뒤에 숨지 않도록 — impact_ai_guide 규약).
                logger.warning("summary insight 섹션 '%s' enrichment 실패 — 결정론 폴백", name, exc_info=True)
                reason = "llm_error"
        if name == "roles":
            fallback = _deterministic_role_guidance(det, inp)
            out_sections[name] = (
                {"ai_enriched": True, "reason": None, **enriched}
                if enriched else {"ai_enriched": False, "reason": reason, **fallback}
            )
        else:
            out_sections[name] = (
                {"ai_enriched": True, "reason": None, "items": enriched}
                if enriched else {"ai_enriched": False, "reason": reason, "items": []}
            )

    model = resolve_effective_model(cfg)
    return {
        "ok": True,
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "ai_enriched": any(s.get("ai_enriched") for s in out_sections.values()),
        "cache_key": compute_cache_key(inp, model or ""),
        "input": {
            "job_slug": inp.job_slug,
            "latest_build": inp.latest_build,
            "baseline_build": inp.baseline_build,
            "excerpt_files": [e.get("path") for e in inp.code_excerpts],
        },
        "deterministic": det,
        "sections": out_sections,
    }
