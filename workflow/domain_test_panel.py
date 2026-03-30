# domain_test_panel.py
# -*- coding: utf-8 -*-
"""
범용 도메인 유닛테스트 생성 패널

특징
- 특정 코드 파일(예: e2e.c, gateway_logic.c 등)에 대해
  1) 도메인 시나리오 설계
  2) 엣지케이스 보강
  3) 유닛테스트 코드 생성
- LLM 호출 방법/환경에는 의존하지 않음
  → llm_call(messages: List[dict]) -> str 콜백만 넘겨주면 됨
- C 프로젝트를 기본 대상으로 설계, 다른 언어도 language/test_framework 파라미터로 확장 가능
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 데이터 모델
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    id: str
    title: str
    given: str
    when: str
    then: str
    tags: List[str] = field(default_factory=list)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Scenario":
        """외부 JSON → Scenario 객체 변환"""
        return Scenario(
            id=str(d.get("id") or d.get("name") or d.get("title") or "S-1"),
            title=str(d.get("title") or d.get("name") or "Unnamed Scenario"),
            given=str(d.get("given") or d.get("precondition") or ""),
            when=str(d.get("when") or d.get("action") or ""),
            then=str(d.get("then") or d.get("assertion") or d.get("expected") or ""),
            tags=list(d.get("tags") or []),
        )


@dataclass
class DomainTestConfig:
    language: str = "c"                     # "c", "cpp", "python" 등
    test_framework: str = "assert"         # "assert", "unity", "gtest" 등
    max_scenarios_per_file: int = 10
    max_source_chars: int = 4000           # 너무 긴 파일 잘라내기
    scenario_style: str = "given-when-then"


# ---------------------------------------------------------------------------
# 유틸 함수
# ---------------------------------------------------------------------------

LLMCall = Callable[[List[Dict[str, str]]], str]


def _read_source(path: Path, limit: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if len(text) > limit:
        return text[:limit] + "\n/* ... truncated ... */\n"
    return text


def _extract_top_level_functions_c(source: str) -> List[str]:
    """
    C 코드에서 대략적인 top-level 함수 이름 추출
    너무 정교할 필요는 없고, 프롬프트 힌트용 정도면 충분
    """
    pattern = re.compile(
        r"^[a-zA-Z_][a-zA-Z0-9_\s\*]+?\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
        re.MULTILINE,
    )
    names: List[str] = []
    for m in pattern.finditer(source):
        name = m.group(1)
        if name not in names:
            names.append(name)
    return names


def _try_parse_json_block(text: str) -> Any:
    """
    LLM이 ```json ... ``` 으로 감싼 경우까지 포함해서 최대한 JSON 파싱 시도
    실패하면 None 반환
    """
    # 코드펜스 안의 json 우선 탐색
    fence_match = re.search(r"```json(.*?)```", text, re.DOTALL | re.IGNORECASE)
    candidates: List[str] = []
    if fence_match:
        candidates.append(fence_match.group(1))

    # 전체 텍스트도 후보
    candidates.append(text)

    for c in candidates:
        c = c.strip()
        # 리스트나 객체만 남도록 앞뒤 잡소리 제거 시도
        first = c.find("[")
        brace = c.find("{")
        start = None
        if first == -1 and brace == -1:
            continue
        if first == -1:
            start = brace
        elif brace == -1:
            start = first
        else:
            start = min(first, brace)
        c2 = c[start:]
        # 뒤에서부터 ],} 탐색
        last_arr = c2.rfind("]")
        last_obj = c2.rfind("}")
        end = max(last_arr, last_obj)
        if end <= 0:
            continue
        c2 = c2[: end + 1]
        try:
            return json.loads(c2)
        except Exception:
            continue
    return None


def _scenarios_from_llm_json(raw: str) -> List[Scenario]:
    data = _try_parse_json_block(raw)
    if data is None:
        return []

    scenarios: List[Scenario] = []
    if isinstance(data, dict) and "scenarios" in data:
        items = data["scenarios"]
    elif isinstance(data, list):
        items = data
    else:
        return []

    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        s = Scenario.from_dict(item)
        if not s.id:
            s.id = f"S-{idx}"
        scenarios.append(s)
    return scenarios


# ---------------------------------------------------------------------------
# 에이전트 프롬프트
# ---------------------------------------------------------------------------

def _make_system_prompt_scenario(language: str) -> str:
    return (
        "You are a senior software engineer and test architect.\n"
        "Your job is to design high-value unit test scenarios for the given code.\n"
        f"The target language is {language}. "
        "Focus on realistic behaviors, boundary conditions, and failure modes.\n"
        "Output the result strictly in JSON with the following structure:\n"
        "{ \"scenarios\": [ {"
        "\"id\": \"S-1\", "
        "\"title\": \"short title\", "
        "\"given\": \"precondition\", "
        "\"when\": \"action\", "
        "\"then\": \"expected outcome\", "
        "\"tags\": [\"normal\", \"edge\", \"error-handling\"]"
        "} ] }\n"
    )


def _make_user_prompt_scenario(
    path: Path,
    source_excerpt: str,
    functions: List[str],
    domain_notes: Optional[str],
    max_scenarios: int,
) -> str:
    fn_part = ", ".join(functions[:10]) if functions else "(no function parsed)"
    dn = domain_notes or "No additional domain description was provided."
    return (
        f"Target file: {path.name}\n"
        f"Approximate top-level functions: {fn_part}\n\n"
        "Domain context:\n"
        f"{dn}\n\n"
        "Source excerpt:\n"
        "------------------------\n"
        f"{source_excerpt}\n"
        "------------------------\n\n"
        f"Design up to {max_scenarios} high-value unit test scenarios for this file.\n"
        "Mix normal flows, boundary conditions, and error cases.\n"
    )


def _make_system_prompt_edge(language: str) -> str:
    return (
        "You are an experienced QA engineer.\n"
        "You will receive an existing list of unit test scenarios for some code.\n"
        "Your task is to add missing edge cases, extreme inputs, and failure scenarios.\n"
        "Do NOT repeat existing scenarios. Instead, extend the list.\n"
        "Output the merged scenarios as strict JSON with the same structure as input:\n"
        "{ \"scenarios\": [ {\"id\": \"S-1\", \"title\": \"...\", \"given\": \"...\", \"when\": \"...\", \"then\": \"...\", \"tags\": [\"edge\"] } ] }\n"
    )


def _make_user_prompt_edge(scenarios: List[Scenario]) -> str:
    data = {"scenarios": [asdict(s) for s in scenarios]}
    return (
        "Here is the current list of scenarios in JSON:\n"
        f"{json.dumps(data, indent=2)}\n\n"
        "Extend this list with additional edge cases and failure scenarios.\n"
        "Use IDs that do not clash with existing ones (e.g., S-101, S-102).\n"
    )


def _make_system_prompt_test_writer(language: str, framework: str) -> str:
    base = (
        "You are a test engineer.\n"
        "You will receive a list of domain test scenarios for a single source file.\n"
        "Your job is to write compilable unit test code that implements these scenarios.\n"
        "Follow these rules strictly:\n"
        "- One test function per scenario.\n"
        "- Include comments with the scenario ID and title.\n"
        "- Make reasonable assumptions about function signatures if not fully known.\n"
    )
    if language.lower() == "c":
        if framework == "unity":
            extra = (
                "- Use the Unity test framework.\n"
                "- Include <unity.h> and use TEST_GROUP/TEST/TEST_SETUP if appropriate.\n"
            )
        else:
            extra = (
                "- Use plain C with <assert.h> only.\n"
                "- No external dependencies or runtime frameworks.\n"
            )
    else:
        extra = f"- Target language: {language}. Use a minimal test style with assertions.\n"
    return base + extra


def _make_user_prompt_test_writer(
    path: Path,
    scenarios: List[Scenario],
    functions: List[str],
    language: str,
    framework: str,
) -> str:
    data = {"scenarios": [asdict(s) for s in scenarios]}
    fn_part = ", ".join(functions[:10]) if functions else "(no function parsed)"
    return (
        f"Target file: {path.name}\n"
        f"Language: {language}\n"
        f"Test framework: {framework}\n"
        f"Approximate top-level functions: {fn_part}\n\n"
        "Scenarios JSON:\n"
        f"{json.dumps(data, indent=2)}\n\n"
        "Now write the complete unit test source file.\n"
        "Do not wrap it in markdown fences. Output only the source code.\n"
    )


# ---------------------------------------------------------------------------
# 에이전트 실행 함수
# ---------------------------------------------------------------------------

def _agent_scenario_architect(
    file_path: Path,
    source_excerpt: str,
    functions: List[str],
    cfg: DomainTestConfig,
    llm_call: LLMCall,
    domain_notes: Optional[str],
) -> List[Scenario]:
    messages = [
        {"role": "system", "content": _make_system_prompt_scenario(cfg.language)},
        {
            "role": "user",
            "content": _make_user_prompt_scenario(
                file_path,
                source_excerpt,
                functions,
                domain_notes,
                cfg.max_scenarios_per_file,
            ),
        },
    ]
    raw = llm_call(messages)
    scenarios = _scenarios_from_llm_json(raw)
    return scenarios


def _agent_edge_case_hunter(
    scenarios: List[Scenario],
    cfg: DomainTestConfig,
    llm_call: LLMCall,
) -> List[Scenario]:
    if not scenarios:
        return scenarios
    messages = [
        {"role": "system", "content": _make_system_prompt_edge(cfg.language)},
        {"role": "user", "content": _make_user_prompt_edge(scenarios)},
    ]
    raw = llm_call(messages)
    extra = _scenarios_from_llm_json(raw)
    # 기존 + 추가 합치기 (id 기준으로 중복 제거)
    merged: Dict[str, Scenario] = {s.id: s for s in scenarios}
    for s in extra:
        if s.id in merged:
            # ID 충돌 시 뒤에 붙이기
            base = s.id
            i = 1
            new_id = f"{base}_{i}"
            while new_id in merged:
                i += 1
                new_id = f"{base}_{i}"
            s.id = new_id
        merged[s.id] = s
    return list(merged.values())


def _agent_test_writer(
    file_path: Path,
    scenarios: List[Scenario],
    functions: List[str],
    cfg: DomainTestConfig,
    llm_call: LLMCall,
) -> str:
    messages = [
        {"role": "system", "content": _make_system_prompt_test_writer(cfg.language, cfg.test_framework)},
        {
            "role": "user",
            "content": _make_user_prompt_test_writer(
                file_path,
                scenarios,
                functions,
                cfg.language,
                cfg.test_framework,
            ),
        },
    ]
    raw = llm_call(messages)
    # 혹시 코드펜스로 감싸져 있으면 제거
    m = re.search(r"```[a-zA-Z]*\n(.*?)```", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    return raw.strip()


# ---------------------------------------------------------------------------
# 외부에서 쓰는 메인 엔트리
# ---------------------------------------------------------------------------

def run_domain_test_panel(
    project_root: Path | str,
    targets: Iterable[Path | str],
    llm_call: LLMCall,
    config: Optional[DomainTestConfig] = None,
    output_dir: Optional[Path | str] = None,
    domain_notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    범용 도메인 테스트 패널 메인 함수

    Parameters
    ----------
    project_root:
        프로젝트 루트 경로 (로그/상대경로 계산용)
    targets:
        도메인 테스트를 집중적으로 만들고 싶은 소스 파일 목록 (Path 또는 str)
    llm_call:
        LLM 호출 콜백, 시그니처: llm_call(messages: List[dict]) -> str
        - messages 형식은 OpenAI ChatCompletion 스타일 사용
        - cfg 등 환경설정은 closure로 감싸서 사용
    config:
        DomainTestConfig, 없으면 기본값 사용
    output_dir:
        생성된 테스트 파일을 저장할 디렉터리
        None이면 project_root/tests/domain 아래에 저장
    domain_notes:
        선택적 도메인 설명 문자열 (LIN, E2E, 비즈니스 규칙 등)
        없으면 "No additional domain description" 으로 처리

    Returns
    -------
    dict:
        {
          "ok": bool,
          "tests": [
            {
              "target": "libs/e2e.c",
              "test_file": "tests/domain/test_e2e_domain.c",
              "scenario_count": 7
            },
# (trimmed)
          ],
          "errors": [
            {"target": "...", "error": "..."},
# (trimmed)
          ]
        }
    """
    root = Path(project_root)
    cfg = config or DomainTestConfig()
    out_dir = Path(output_dir) if output_dir is not None else (root / "tests" / "domain")
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for t in targets:
        path = Path(t)
        if not path.is_absolute():
            path = root / path
        rel = path.relative_to(root) if path.is_relative_to(root) else path.name

        try:
            source = _read_source(path, cfg.max_source_chars)
            if not source:
                raise RuntimeError("source file not readable or empty")

            if cfg.language.lower() == "c":
                functions = _extract_top_level_functions_c(source)
            else:
                functions = []

            # 1) 시나리오 설계자
            base_scenarios = _agent_scenario_architect(
                file_path=path,
                source_excerpt=source,
                functions=functions,
                cfg=cfg,
                llm_call=llm_call,
                domain_notes=domain_notes,
            )

            # 2) 엣지케이스 헌터
            final_scenarios = _agent_edge_case_hunter(
                scenarios=base_scenarios,
                cfg=cfg,
                llm_call=llm_call,
            )

            if not final_scenarios:
                raise RuntimeError("no scenarios produced by agents")

            # 3) 테스트 코드 작성자
            test_source = _agent_test_writer(
                file_path=path,
                scenarios=final_scenarios,
                functions=functions,
                cfg=cfg,
                llm_call=llm_call,
            )

            test_name = f"test_{path.stem}_domain"
            if cfg.language.lower() == "c":
                test_name += ".c"
            elif cfg.language.lower() == "cpp":
                test_name += ".cpp"
            else:
                # 확장자가 확실치 않으면 그냥 .txt 대신 language 넣기
                test_name += f".{cfg.language}"

            test_path = out_dir / test_name
            test_path.write_text(test_source, encoding="utf-8")

            results.append(
                {
                    "target": str(rel),
                    "test_file": str(test_path.relative_to(root)),
                    "scenario_count": len(final_scenarios),
                }
            )

        except Exception as e:
            errors.append({"target": str(rel), "error": str(e)})

    return {"ok": len(errors) == 0, "tests": results, "errors": errors}