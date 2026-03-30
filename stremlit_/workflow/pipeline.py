# /app/workflow/pipeline.py
# -*- coding: utf-8 -*-
# Integrated DevOps Pipeline
# v31.0: Step 번호 정리, Fuzz/QEMU strict 옵션, AI 로그 컨텍스트/triage 반영
import json
import os
import glob
import shutil
import subprocess
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any, Tuple
from xml.etree import ElementTree as ET

import config
import analysis_tools as tools
# ---------------------------------------------------------------------------
# Fuzz harness generator (minimal, compile-first)
# ---------------------------------------------------------------------------
def _write_fuzz_harness(dst: Path, target_c: Path) -> None:
    """LLVMFuzzerTestOneInput를 포함한 최소 harness 생성
    - 목표: '컴파일/링크 실패'를 줄이고, 플랫폼 종속 코드를 stubs로 우회
    """
    code = f"""// Auto-generated fuzz harness for {target_c.name}
#include <stdint.h>
#include <stddef.h>

// Forward declare entry if desired (not required)
int LLVMFuzzerTestOneInput(const uint8_t *Data, size_t Size) {{
    (void)Data; (void)Size;
    return 0;
}}
"""
    dst.write_text(code, encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or "", encoding="utf-8")
    except Exception:
        pass


def _write_json(path: Path, obj: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _cmake_quote(s: str) -> str:
    """CMake 문자열 리터럴로 안전하게 감싸기 (경로용)."""
    s = (s or "").replace("\\", "/")
    return f'"{s}"'


def _normalize_define(d: str) -> Optional[str]:
    """CLI/환경에서 들어온 define을 CMake target_compile_definitions 입력 형태로 정리."""
    if not d:
        return None
    s = d.strip()
    if not s:
        return None
    if s.startswith("-D"):
        s = s[2:].strip()
    # 공백/따옴표 포함 값은 깨질 수 있어 보수적으로 제외
    if any(ch.isspace() for ch in s):
        return None
    if any(ch in s for ch in ('"', "'")):
        return None
    return s


def _normalize_include_dir(project_root: Path, inc: str) -> Optional[str]:
    """include dir을 CMake에서 쓸 수 있게 정규화.

    - 프로젝트 내부 경로면 ${PROJECT_SOURCE_DIR}/rel 로 변환
    - 절대 경로/외부 경로면 그대로 사용
    """
    if not inc:
        return None
    s = inc.strip().strip('"').strip("'")
    if not s:
        return None
    s = s.replace("\\", "/")

    try:
        p = Path(s)
    except Exception:
        return None

    # 상대경로는 project_root 기준으로 처리
    if not p.is_absolute():
        rel = s.lstrip("./")
        return f"${{PROJECT_SOURCE_DIR}}/{rel}"

    # 절대경로가 project_root 하위면 상대화
    try:
        relp = p.resolve().relative_to(project_root.resolve())
        # NOTE: avoid backslashes inside f-string expressions (SyntaxError on some Python versions)
        return f"${{PROJECT_SOURCE_DIR}}/{relp.as_posix()}"
    except Exception:
        return s


def _has_test_main_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return bool(re.search(r"\bmain\s*\(", text))


def _generate_auto_generated_cmakelists(
    project_root: Path,
    reports: Path,
    tests_summary: Dict[str, Any],
    include_paths: List[str],
    defines: List[str],
    stubs_root: str,
) -> Dict[str, Any]:
    """AI가 생성한 test_*.c/cpp를 CTest에서 실행 가능하도록
    reports/auto_generated/CMakeLists.txt를 자동 생성.

    - _invalid/_archive 제외
    - syntax_ok(=result.ok=True)만 포함
    - 생성된 매핑을 manifest.json으로 저장
    """
    out: Dict[str, Any] = {"generated": False, "count": 0, "path": None, "manifest": None, "prefix": None}

    tests_dir = reports / "auto_generated"
    tools.ensure_dir(tests_dir)

    results = (tests_summary or {}).get("results", [])
    if not isinstance(results, list):
        results = []

    # 유효 테스트 소스 수집
    test_files: List[Path] = []
    for r in results:
        try:
            if not r.get("ok"):
                continue
            tf = r.get("test_file")
            if not tf:
                continue
            p = Path(tf)
            # _invalid / _archive 경로 제외
            if "_invalid" in p.parts or "_archive" in p.parts:
                continue
            # auto_generated 폴더 안쪽만 허용
            try:
                p.resolve().relative_to(tests_dir.resolve())
            except Exception:
                continue
            if p.suffix.lower() not in (".c", ".cpp", ".cc", ".cxx"):
                continue
            if p.exists() and _has_test_main_file(p):
                test_files.append(p)
        except Exception:
            continue

    # test_*.c/cpp glob도 병행 (결과 dict 누락 대비)
    for p in list(tests_dir.glob("test_*.c")) + list(tests_dir.glob("test_*.cpp")):
        if "_invalid" in p.parts or "_archive" in p.parts:
            continue
        if not _has_test_main_file(p):
            continue
        if p not in test_files:
            test_files.append(p)

    # 정렬(결정성)
    test_files = sorted(test_files, key=lambda x: x.name)

    # If no valid tests, remove stale CMakeLists/manifest to avoid CMake configure failure
    if not test_files:
        stale_cmake = tests_dir / "CMakeLists.txt"
        stale_manifest = tests_dir / "manifest.json"
        for sp in (stale_cmake, stale_manifest):
            try:
                if sp.exists():
                    sp.unlink()
            except Exception:
                pass
        out["generated"] = False
        out["count"] = 0
        out["path"] = None
        out["manifest"] = None
        out["reason"] = "no_valid_tests"
        return out


    cmake_path = tests_dir / "CMakeLists.txt"
    manifest_path = tests_dir / "manifest.json"

    if not test_files:
        # stale 파일 제거
        try:
            cmake_path.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass
        try:
            manifest_path.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass
        out.update({"generated": False, "count": 0, "path": None, "manifest": None, "reason": "no_valid_tests"})
        return out

    # include paths 정리
    incs: List[str] = []
    # 기본 include (프로젝트 구조 힌트)
    base_incs = [
        "${PROJECT_SOURCE_DIR}",
        "${PROJECT_SOURCE_DIR}/libs",
        "${PROJECT_SOURCE_DIR}/tests",
        f"${{PROJECT_SOURCE_DIR}}/{stubs_root.strip('/')}" if stubs_root else "${PROJECT_SOURCE_DIR}/tests/stubs",
    ]
    for b in base_incs:
        if b and b not in incs:
            incs.append(b)

    for inc in include_paths or []:
        ni = _normalize_include_dir(project_root, inc)
        if ni and ni not in incs:
            incs.append(ni)

    # define 정리
    defs: List[str] = []
    for d in ["UNIT_TEST", "HOST_BUILD"] + list(defines or []):
        nd = _normalize_define(d)
        if nd and nd not in defs:
            defs.append(nd)

    # target/test name 매핑 구성
    prefix = "ai_ut_"
    out["prefix"] = prefix
    manifest: List[Dict[str, Any]] = []
    used: Dict[str, int] = {}

    for p in test_files:
        stem = p.stem
        # test_foo -> foo
        if stem.startswith("test_"):
            stem = stem[len("test_") :]
        # CMake target name safe
        safe = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in stem)
        if not safe:
            safe = "test"
        name = f"{prefix}{safe}"
        n = used.get(name, 0)
        if n:
            name = f"{name}_{n+1}"
        used[name] = used.get(name, 0) + 1

        manifest.append(
            {
                "source": str(p.name),
                "target": name,
                "ctest_name": name,
                "language": "C++" if p.suffix.lower() in (".cpp", ".cc", ".cxx") else "C",
            }
        )

    # CMakeLists 생성
    lines: List[str] = []
    lines.append("# Auto-generated by workflow pipeline (P2.1)")
    lines.append("# Do NOT edit manually. This file is regenerated on each run.")
    lines.append("cmake_minimum_required(VERSION 3.15)")
    lines.append("include(CTest)")
    lines.append("enable_testing()")
    lines.append("")

    lines.append("set(_AI_AUTOGEN_TEST_SOURCES")
    for m in manifest:
        lines.append(f"  ${{CMAKE_CURRENT_LIST_DIR}}/{m['source']}")
    lines.append(")")
    lines.append("")

    # include dirs
    lines.append("set(_AI_AUTOGEN_TEST_INCLUDES")
    for inc in incs:
        lines.append(f"  {_cmake_quote(inc)}")
    lines.append(")")
    lines.append("")

    # compile defs
    lines.append("set(_AI_AUTOGEN_TEST_DEFS")
    for d in defs:
        lines.append(f"  {_cmake_quote(d)}")
    lines.append(")")
    lines.append("")

    # manifest-driven explicit targets (결정성 + 중복 처리)
    for m in manifest:
        src = f"${{CMAKE_CURRENT_LIST_DIR}}/{m['source']}"
        tgt = m["target"]
        # Guard missing sources to avoid CMake configure failure
        lines.append(f"set(_AI_SRC_{tgt} {src})")
        lines.append(f"if(EXISTS ${{_AI_SRC_{tgt}}})")
        lines.append(f"  add_executable({tgt} ${{_AI_SRC_{tgt}}})")
        lines.append(f"  target_include_directories({tgt} PRIVATE ${{_AI_AUTOGEN_TEST_INCLUDES}})")
        lines.append(f"  target_compile_definitions({tgt} PRIVATE ${{_AI_AUTOGEN_TEST_DEFS}})")
        lines.append(f"  if(TARGET lin_gateway_lib)")
        lines.append(f"    target_link_libraries({tgt} PRIVATE lin_gateway_lib)")
        lines.append("  endif()")
        lines.append(f"  add_test(NAME {tgt} COMMAND {tgt})")
        lines.append("else()")
        lines.append(f"  message(WARNING \"[auto_generated] missing source: ${{_AI_SRC_{tgt}}}, skipping {tgt}\")")
        lines.append("endif()")
        lines.append("")

    content = "\n".join(lines) + "\n"
    tmp = cmake_path.with_suffix(".txt.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(cmake_path)
        out["generated"] = True
        out["count"] = len(manifest)
        out["path"] = str(cmake_path)
    except Exception as e:
        out.update({"generated": False, "count": 0, "path": None, "reason": f"write_error: {e}"})
        return out

    # manifest 저장
    try:
        _write_json(manifest_path, {"generated_at": datetime.now().isoformat(), "prefix": prefix, "items": manifest})
        out["manifest"] = str(manifest_path)
    except Exception:
        out["manifest"] = None

    return out


def _attach_ai_test_execution_to_summary(tests_summary: Dict[str, Any], b_res: Dict[str, Any]) -> None:
    """build.build_and_tests()의 ctest_results를 이용해 AI 생성 테스트 실행 결과를 tests_summary에 부착."""
    if not tests_summary or not tests_summary.get("enabled"):
        return

    cm = tests_summary.get("cmake") or {}
    prefix = cm.get("prefix") or "ai_ut_"
    ctest_results = (b_res or {}).get("data", {}).get("ctest_results", [])
    if not isinstance(ctest_results, list):
        ctest_results = []

    ai_runs: List[Dict[str, Any]] = []
    for r in ctest_results:
        try:
            name = r.get("name")
            if not name or not isinstance(name, str):
                continue
            if not name.startswith(prefix):
                continue
            ai_runs.append(
                {
                    "name": name,
                    "status": r.get("status"),
                    "exit_code": r.get("exit_code"),
                    "output": r.get("output"),
                }
            )
        except Exception:
            continue

    passed = sum(1 for x in ai_runs if x.get("status") == "pass")
    failed = sum(1 for x in ai_runs if x.get("status") != "pass")

    reason = "completed"
    if not (b_res or {}).get("ok") and (b_res or {}).get("reason") != "skipped":
        reason = "build_or_tests_failed"
    if cm.get("generated") and int(cm.get("count") or 0) > 0 and len(ai_runs) == 0:
        reason = "no_ai_tests_found_in_ctest"

    tests_summary["execution"] = {
        "enabled": True,
        "reason": reason,
        "count": len(ai_runs),
        "passed": passed,
        "failed": failed,
        "ok": (failed == 0),
        "results": ai_runs,
        "note": "AI auto-generated tests executed via CTest",
    }


def _detect_clang_info() -> Dict[str, str]:
    info: Dict[str, str] = {}
    try:
        v = subprocess.check_output(["clang", "--version"], text=True, stderr=subprocess.STDOUT).strip()
        info["clang_version"] = v.splitlines()[0] if v else ""
    except Exception:
        info["clang_version"] = ""
    try:
        r = subprocess.check_output(["clang", "-print-resource-dir"], text=True, stderr=subprocess.STDOUT).strip()
        info["clang_resource_dir"] = r
    except Exception:
        info["clang_resource_dir"] = ""
    return info

# NOTE:
# - This module is normally imported as a package member (workflow.pipeline).
# - When opened/executed as a standalone file (e.g., some IDE tools), relative
#   imports may fail. Keep a small absolute-import fallback for developer UX.

try:
    from . import common, static, build, ai, rag
    from .domain_test_panel import run_domain_test_panel, DomainTestConfig
except Exception:  # pragma: no cover
    import common, static, build, ai, rag  # type: ignore
    from domain_test_panel import run_domain_test_panel, DomainTestConfig  # type: ignore


def _csv_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        out = []
        for x in v:
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    s = str(v).strip()
    if not s:
        return []
    parts = re.split(r"[,\n]+", s)
    return [p.strip() for p in parts if p.strip()]


def _pick_best_rag_solution(past_solutions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not past_solutions:
        return None
    try:
        return sorted(past_solutions, key=lambda x: float(x.get("score", 0.0)), reverse=True)[0]
    except Exception:
        return past_solutions[0]


def _extract_search_replace_blocks_text(text: str, max_blocks: int = 3) -> Optional[str]:
    """
    RAG fix pattern에서 SEARCH/REPLACE 블록을 최대 max_blocks개까지 추출해
    ai.apply_patch()가 처리 가능한 포맷으로 재구성
    """
    if not text or max_blocks <= 0:
        return None

    # ai._parse_search_replace_blocks와 호환되는 포맷
    pattern = re.compile(
        r"<<<<SEARCH_BLOCK\[(?P<file>[^\]]+)\]\s*\n(?P<search>.*?)\n<<<<REPLACE_BLOCK\[(?P=file)\]\s*\n(?P<replace>.*?)(?=\n<<<<SEARCH_BLOCK\[|\Z)",
        re.DOTALL,
    )

    blocks: List[str] = []
    for m in pattern.finditer(text):
        file = (m.group("file") or "").strip()
        search = (m.group("search") or "").rstrip("\n")
        repl = (m.group("replace") or "").rstrip("\n")
        if not file:
            continue
        blocks.append(f"<<<<SEARCH_BLOCK[{file}]\n{search}\n<<<<REPLACE_BLOCK[{file}]\n{repl}\n")
        if len(blocks) >= max_blocks:
            break

    if not blocks:
        return None
    return "\n".join(blocks).strip() + "\n"


def _llm_call_with_policy(
    cfg_primary: Dict[str, Any],
    cfg_fallbacks: List[Dict[str, Any]],
    messages: List[Dict[str, str]],
    log_dir: Path,
    *,
    total_attempts: int,
    fallback_models: List[str],
    fallback_config_paths: List[str],
    stage: Optional[str] = None,
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    - 동일 요청 2회 재시도 (primary 2회)
    - 이후 fallback 모델/설정으로 순차 시도
    - 각 시도에 대한 메타를 리스트로 반환
    """
    attempts_meta: List[Dict[str, Any]] = []

    candidates: List[tuple[str, Dict[str, Any]]] = [("primary", dict(cfg_primary))]
    # config list의 2번째~ 항목들도 fallback 후보로 사용
    for i, c in enumerate(cfg_fallbacks or []):
        if isinstance(c, dict) and c:
            candidates.append((f"config_list[{i+1}]", dict(c)))

    for m in fallback_models:
        try:
            c = dict(cfg_primary)
            c["model"] = m
            candidates.append((f"fallback_model:{m}", c))
        except Exception:
            continue

    for p in fallback_config_paths:
        try:
            c2 = ai.load_oai_config(p)
            if isinstance(c2, dict) and c2:
                candidates.append((f"fallback_cfg:{p}", dict(c2)))
        except Exception:
            continue

    if total_attempts <= 0:
        total_attempts = 1

    schedule: List[tuple[str, Dict[str, Any]]] = []
    # 1) same request retry twice on primary
    schedule.append(candidates[0])
    if total_attempts >= 2:
        schedule.append(candidates[0])

    # 2) then try remaining candidates
    for cand in candidates[1:]:
        if len(schedule) >= total_attempts:
            break
        schedule.append(cand)

    # 3) pad if still short
    while len(schedule) < total_attempts:
        schedule.append(schedule[-1])

    reply: Optional[str] = None
    for idx, (label, cfg_use) in enumerate(schedule[:total_attempts], start=1):
        meta: Dict[str, Any] = {"policy_attempt": idx, "label": label}
        t0 = time.time()
        try:
            reply = ai.llm_call(cfg_use, messages, log_dir, meta_out=meta, stage=stage)
        except Exception as e:
            meta["error"] = str(e)
            reply = None
        meta["duration_sec"] = round(time.time() - t0, 3)
        attempts_meta.append(meta)
        if reply:
            break

    return reply, attempts_meta


def _resolve_patch_mode(patch_mode: Optional[str]) -> str:
    """
    AGENT 패치 모드 정규화
    - 우선순위: run_cli 인자 > 환경변수 AGENT_PATCH_MODE > config.AGENT_PATCH_MODE_DEFAULT > 'auto'
    - 허용 값: ['auto', 'review', 'off']
    """
    valid = getattr(config, "AGENT_PATCH_MODES", ["auto", "review", "off"])
    default = getattr(config, "AGENT_PATCH_MODE_DEFAULT", "auto")

    mode = patch_mode or os.environ.get("AGENT_PATCH_MODE") or default
    if not mode:
        return default

    mode = mode.lower()
    if mode not in valid:
        return default
    return mode


def _save_agent_patch(
    reports: Path,
    content: str,
    iteration: int,
    fix_mode: str,
) -> Path:
    """
    review 모드용 패치 제안 저장 헬퍼
    - LLM이 뱉은 SEARCH/REPLACE 블록 원문을 그대로 텍스트로 저장
    - 실제 코드 수정은 전혀 하지 않음
    """
    patch_dir = reports / "agent_patches"
    tools.ensure_dir(patch_dir)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"agent_patch_iter{iteration}_{fix_mode}_{ts}.txt"
    path = patch_dir / name
    tmp = path.with_suffix(path.suffix + ".tmp")

    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        print(f"[WARN] Failed to save agent patch file: {e}")

    return path


def _pick_runtime_targets(targets: List[Path], all_targets: List[Path]) -> List[Path]:
    return targets if targets else all_targets


def _has_libfuzzer_runtime() -> bool:
    """
    컨테이너에 libFuzzer/ASan용 clang runtime 존재 여부 체크, clang이 실제 사용하는 resource-dir 기준

    문제 사례
    - /usr/lib/llvm-16/... 에는 런타임 존재
    - clang 버전은 환경에 따라 18/19 등 변동, resource-dir는 clang -print-resource-dir 기반
    - 결과적으로 링크 단계에서 libclang_rt.* 누락, fuzz 단계 FAIL인데 로그상 PASS로 보이는 현상

    체크 기준
    - clang 실행 가능
    - clang -print-resource-dir 아래에 fuzzer/asan 런타임 아카이브 존재
    """
    if not shutil.which("clang"):
        return False

    resource_dir: Optional[str] = None
    try:
        resource_dir = subprocess.check_output(  # nosec - local tool call
            ["clang", "-print-resource-dir"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        resource_dir = None

    search_roots: List[Path] = []
    if resource_dir:
        rd = Path(resource_dir)
        lib_root = rd / "lib"
        if lib_root.is_dir():
            search_roots.append(lib_root)

    # fallback (resource-dir 조회 실패 대비)
    for p in (
        "/usr/lib/llvm-*/lib/clang/*/lib",
        "/usr/lib/clang/*/lib",
    ):
        for hit in glob.glob(p):
            try:
                hp = Path(hit)
                if hp.is_dir():
                    search_roots.append(hp)
            except Exception:
                pass

    if not search_roots:
        return False

    def _glob_any(root: Path, pat: str) -> bool:
        try:
            return bool(list(root.glob(pat)))
        except Exception:
            return False

    has_fuzzer = any(_glob_any(r, "**/libclang_rt.fuzzer*.a") for r in search_roots)
    has_asan = any(_glob_any(r, "**/libclang_rt.asan*.a") for r in search_roots)

    return bool(has_fuzzer and has_asan)


def _resolve_qemu_elf(proj: Path, build_dir: Optional[Path]) -> Optional[Path]:
    """
    QEMU 실행에 사용할 ELF 탐색
    우선순위
    1) 환경변수 QEMU_ELF_NAME
    2) config.QEMU_ELF_NAME
    3) config.QEMU_ELF_CANDIDATES
    4) 기본 후보: lin_gateway_rp2040.elf, my_lin_gateway.elf
    5) 위 후보가 없으면 *.elf 아무거나
    """
    elf_name = os.environ.get("QEMU_ELF_NAME") or getattr(config, "QEMU_ELF_NAME", None)
    candidates = []
    if elf_name:
        candidates.append(elf_name)

    candidates += list(getattr(config, "QEMU_ELF_CANDIDATES", []))
    if not candidates:
        candidates = ["lin_gateway_rp2040.elf", "my_lin_gateway.elf"]

    # 중복 제거
    uniq = []
    seen = set()
    for c in candidates:
        if c and c not in seen:
            uniq.append(c)
            seen.add(c)
    candidates = uniq

    search_roots: List[Path] = []
    if build_dir:
        search_roots.append(build_dir)
    # 프로젝트 전역도 탐색
    search_roots.append(proj)
    # 흔한 빌드 위치 힌트
    if (proj / "build").exists():
        search_roots.append(proj / "build")
    if (proj / "reports").exists():
        search_roots.append(proj / "reports")

    for cand in candidates:
        for root in search_roots:
            if root and root.exists():
                hits = list(root.rglob(cand))
                if hits:
                    return hits[0]

    # 후보명 실패 시 *.elf fallback
    for root in search_roots:
        if root and root.exists():
            elfs = list(root.rglob("*.elf"))
            if elfs:
                return elfs[0]

    return None



def _is_truthy(val: str) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _is_ci_env() -> bool:
    # Common CI markers
    if os.environ.get("JENKINS_URL") or os.environ.get("JENKINS_HOME"):
        return True
    for k in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "TF_BUILD"):
        if _is_truthy(os.environ.get(k, "")):
            return True
    return False


def _env_flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return _is_truthy(v)


def _read_text_safe(p: Path, limit_chars: int = 0) -> str:
    try:
        s = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if limit_chars and len(s) > limit_chars:
        return s[:limit_chars] + "\n... (truncated)\n"
    return s


def _extract_interesting_lines(text: str, max_lines: int = 140) -> str:
    """에러 원인 파악에 도움이 되는 라인만 추출"""
    if not text:
        return ""
    needles = (
        "error:",
        "fatal:",
        "undefined reference",
        "ld:",
        "collect2:",
        "Assertion",
        "assertion",
        "AddressSanitizer",
        "ThreadSanitizer",
        "runtime error",
        "SIGSEGV",
        "Segmentation fault",
        "Timeout",
        "TIMEOUT",
        "FAILED",
        "failed",
        "No such file or directory",
    )
    out: List[str] = []
    for ln in text.splitlines():
        if any(n in ln for n in needles):
            out.append(ln)
            if len(out) >= max_lines:
                break
    return "\n".join(out)


def _build_ai_context_for_build_failure(
    proj: Path,
    b_res: Dict[str, Any],
    max_chars: int = 12000,
) -> Dict[str, str]:
    """
    build/test 실패 시 AI에 넘길 프롬프트 컨텍스트를 구성
    - triage 요약
    - 실패 테스트별 출력 파일 일부
    - 에러 라인 추출 + 로그 tail
    """
    data = b_res.get("data", {}) or {}
    triage = data.get("triage", {}) or {}
    failures = triage.get("failures", []) or []
    targets = triage.get("targets", []) or []
    timeout_tests = triage.get("timeout_tests", []) or []

    ctest_results = data.get("ctest_results", []) or []
    failing_tests = [
        r
        for r in ctest_results
        if int(r.get("exit_code", 0) or 0) != 0 and r.get("output")
    ][:6]

    build_ok = bool(data.get("build_ok", False))
    tests_ok = bool(data.get("tests_ok", True))
    reason = b_res.get("reason", "")

    mode = "build_compile"
    if build_ok and not tests_ok:
        mode = "unit_test_fail"
    elif reason == "config_fail":
        mode = "cmake_config_fail"

    # policy (prod-first)
    policy = (
        "Fix policy:\n"
        "- unit test 실패라면 기본은 프로덕션 코드(libs/) 수정 우선\n"
        "- 테스트/스텁 수정은 '테스트 코드 자체의 문법/컴파일 오류' 또는 '스텁 누락'이 명백할 때만\n"
        "- 테스트를 비활성화하거나 기대값을 약화시키지 말 것\n"
        "- 출력은 SEARCH/REPLACE 블록만\n"
    )

    triage_lines = []
    for f in failures[:6]:
        t = f.get("type", "")
        h = f.get("hint", "")
        if t or h:
            triage_lines.append(f"- {t}: {h}".strip())
    if timeout_tests:
        triage_lines.append(f"- timeout_tests: {', '.join(timeout_tests[:8])}")

    focus_files = []
    for t in targets[:8]:
        fp = (proj / t).resolve()
        if proj in fp.parents and fp.exists():
            focus_files.append(str(fp.relative_to(proj)))
    focus_files = focus_files[:8]

    header = (
        f"Build/Test Failure Mode: {mode}\n"
        f"Reason: {reason}\n"
        f"build_ok={build_ok}, tests_ok={tests_ok}\n"
        + ("\n[Triage]\n" + "\n".join(triage_lines) + "\n" if triage_lines else "")
        + ("\n[Suggested Focus Files]\n" + "\n".join(focus_files) + "\n" if focus_files else "")
        + "\n"
        + policy
    )

    # excerpts for suggested targets
    excerpts: Dict[str, str] = {}
    for rel in focus_files[:4]:
        excerpts[rel] = common.read_excerpt(proj / rel)

    log_text = data.get("log", "") or ""
    interesting = _extract_interesting_lines(log_text, max_lines=160)
    tail = log_text[-6000:] if len(log_text) > 6000 else log_text

    sections: List[str] = [header]
    if excerpts:
        sections.append("[Source Excerpts]\n" + json.dumps(excerpts, indent=2))

    # failing test outputs
    for r in failing_tests:
        name = r.get("name") or "__all__"
        outp = Path(str(r.get("output")))
        out_txt = _read_text_safe(outp, limit_chars=2500)
        sections.append(
            f"[CTest Output: {name} | status={r.get('status')} | exit={r.get('exit_code')}]\n{out_txt}"
        )

    if interesting:
        sections.append("[Interesting Log Lines]\n" + interesting)
    if tail:
        sections.append("[Build Log Tail]\n" + tail)

    # fit to budget while preserving header
    combined = sections[0]
    budget = max_chars - len(combined)
    for sec in sections[1:]:
        if budget <= 0:
            break
        if len(sec) + 2 <= budget:
            combined += "\n\n" + sec
            budget -= (len(sec) + 2)
        else:
            # partial append
            combined += "\n\n" + sec[: max(0, budget)]
            budget = 0
            break

    # rag key는 너무 길지 않게
    rag_key = ""
    if failures:
        rag_key = (failures[0].get("type", "") + " " + failures[0].get("hint", "")).strip()
    if not rag_key:
        rag_key = (interesting.splitlines()[0] if interesting else tail.splitlines()[-1] if tail else "")[:300]

    return {
        "context": combined,
        "rag_key": rag_key[:300],
        "mode": mode,
    }



def run_cli(
    project_root: str,
    report_dir: str = "reports",
    targets_glob: str = "libs/*.c",
    include_paths: Optional[List[str]] = None,
    suppressions_path: Optional[str] = None,
    # Flags
    do_cmake_analysis: bool = False,  # 현재 단계에서는 미사용, 인터페이스 유지용
    do_syntax_check: bool = True,
    do_build_and_test: bool = False,
    do_coverage: bool = False,
    static_only: bool = True,
    enable_agent: bool = False,
    max_iterations: int = 1,
    oai_config_path: Optional[str] = None,
    pico_sdk_path_override: Optional[str] = None,
    auto_guard: bool = False,
    guard_prefixes: Optional[List[str]] = None,
    stubs_root: str = "tests/stubs",
    dry_run_autoguard: bool = False,
    defines: Optional[List[str]] = None,
    full_analysis: bool = False,
    # Callbacks
    progress_callback: Optional[Callable] = None,
    log_callback: Optional[Callable] = None,
    # Configs
    target_arch: str = "cortex-m0plus",
    extra_defines: Optional[List[str]] = None,
    cppcheck_enable: Optional[List[str]] = None,
    enable_test_gen: bool = False,
    do_clang_tidy: bool = False,
    clang_tidy_checks: Optional[List[str]] = None,
    # Dynamic Analysis Flags
    do_asan: bool = False,
    do_fuzz: bool = False,
    do_qemu: bool = False,
    do_docs: bool = False,
    # Domain Test Options
    enable_domain_tests: bool = False,
    domain_targets: Optional[List[str]] = None,
    # Agent patch mode (auto / review / off)
    patch_mode: Optional[str] = None,
    # Agent loop settings
    agent_roles: Optional[List[str]] = None,
    agent_review: Optional[bool] = None,
    agent_rag: Optional[bool] = None,
    agent_max_steps: Optional[int] = None,
    agent_run_mode: Optional[str] = None,
    agent_rag_top_k: Optional[int] = None,
    # [NEW] 정적 분석 실패 무시 여부 (기본값 False)
    ignore_static_failure: bool = False,
    ai_log_max_chars: int = 12000,
    fuzz_strict: Optional[bool] = None,
    qemu_strict: Optional[bool] = None,
    domain_tests_strict: Optional[bool] = None,
    # Control
    stop_check: Optional[Callable[[], None]] = None,
    fast_fail: bool = True,
) -> int:
    # 1. Setup & Initialization
    proj = Path(project_root).resolve()
    reports = (proj / report_dir).resolve()
    tools.ensure_dir(reports)
    tools.ensure_dir(reports / "agent_logs")

    def _check_stop() -> None:
        common.check_stop(stop_check=stop_check, stop_flag=(reports / ".stop"))

    _check_stop()


    # strict mode defaults (CI에서는 기본 strict)
    ci_env = _is_ci_env()
    if fuzz_strict is None:
        fuzz_strict = _env_flag("FUZZ_STRICT", default=ci_env)
    if qemu_strict is None:
        qemu_strict = _env_flag("QEMU_STRICT", default=False)
    if domain_tests_strict is None:
        domain_tests_strict = _env_flag("DOMAIN_TESTS_STRICT", default=False)

    # env override for AI log budget
    try:
        _env_ai = int(os.environ.get("AI_LOG_MAX_CHARS", "0") or 0)
        if _env_ai > 0:
            ai_log_max_chars = _env_ai
    except Exception:
        pass

    # AI 로그 budget
    if ai_log_max_chars < 3000:
        ai_log_max_chars = 3000

    if pico_sdk_path_override:
        os.environ["PICO_SDK_PATH"] = pico_sdk_path_override

    # Coverage/ASan을 켜면 빌드 단계 자동 활성화
    if do_coverage or do_asan:
        do_build_and_test = True

    # Initialize Knowledge Base (RAG)
    kb = rag.get_kb(reports)

    # Agent loop configuration
    roles = _csv_list(agent_roles) if agent_roles else []
    if not roles:
        roles = list(getattr(config, "AGENT_ROLES_DEFAULT", ["planner", "generator", "fixer", "reviewer"]))
    agent_settings: Dict[str, Any] = {
        "roles": roles,
        "max_steps": int(agent_max_steps or getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3)),
        "review_enabled": bool(agent_review) if agent_review is not None else bool(getattr(config, "AGENT_REVIEW_ENABLED_DEFAULT", True)),
        "rag_enabled": bool(agent_rag) if agent_rag is not None else bool(getattr(config, "AGENT_RAG_ENABLED_DEFAULT", True)),
        "rag_top_k": int(agent_rag_top_k or getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3)),
        "run_mode": str(agent_run_mode or getattr(config, "AGENT_RUN_MODE_DEFAULT", "auto")),
    }

    # Agent patch 모드 결정
    agent_enabled_effective = bool(enable_agent) and agent_settings.get("run_mode") != "off"
    effective_patch_mode = _resolve_patch_mode(patch_mode) if agent_enabled_effective else "off"
    if agent_settings.get("run_mode") == "review" and agent_enabled_effective:
        effective_patch_mode = "review"

    common.log_msg(log_callback, f"🚀 Analysis started for {proj.name}")
    if agent_enabled_effective:
        common.log_msg(
            log_callback,
            f"🧩 Agent patch mode: {effective_patch_mode}",
        )

    # 2. Target Identification
    all_targets = common.list_targets(proj, targets_glob)
    targets = all_targets
    change_mode = "full"

    if not full_analysis:
        changed_files, git_status = common.get_git_changed_files(proj)
        if git_status == "git_ok":
            targets = [t for t in all_targets if t.resolve() in changed_files]
            change_mode = "incremental"
            common.log_msg(
                log_callback,
                f"ℹ️ Incremental scan: {len(targets)} changed files.",
            )
        else:
            common.log_msg(
                log_callback,
                f"⚠️ Git unavailable ({git_status}), falling back to full scan.",
            )

    # 정적 전용 + 변경 타깃 없음 + 런타임 기능도 없음일 때만 조기 종료
    if (
        not targets
        and static_only
        and not do_build_and_test
        and not do_fuzz
        and not do_qemu
        and not enable_domain_tests
    ):
        common.log_msg(log_callback, "✅ Nothing to analyze.")
        return 0

    # LLM config
    need_llm = agent_enabled_effective or enable_test_gen or do_fuzz or enable_domain_tests
    cfgs = ai.load_oai_configs(oai_config_path) if need_llm else []
    cfg = cfgs[0] if cfgs else None
    cfg_fallbacks = cfgs[1:] if len(cfgs) > 1 else []
    if cfg:
        common.log_msg(log_callback, f"🤖 LLM: model={cfg.get('model')}, api_type={cfg.get('api_type')}")
    
    # 9. Static-Analysis Paths (Moved up for early usage)
    default_incs = getattr(config, "DEFAULT_INCLUDE_PATHS", [])
    inc_paths = list(include_paths or []) + list(default_incs)
    inc_paths += tools.get_arch_include_paths(target_arch, str(proj))
    all_defines = list(defines or []) + list(extra_defines or [])

    # 3. [Step 1] Auto Guard (Stub Injection)
    if auto_guard:
        common.log_msg(log_callback, "🛡️ [Step 1] Auto-Guarding Sources...")
        build.auto_guard_sources(
            proj,
            reports,
            targets,
            guard_prefixes or ["pico/", "hardware/"],
            stubs_root,
            dry_run_autoguard,
            progress_callback,
        )

    # [MOVED UP] 14. [Step 2] Unit Test Generation
    # 커버리지 측정 시 생성된 테스트를 포함하기 위해 빌드 단계 앞으로 이동
    tests_summary: Dict[str, Any] = {"enabled": False}
    if enable_test_gen and cfg:
        common.log_msg(
            log_callback,
            "🧪 [Step 2] Generating Unit Tests (Pre-Build)...",
        )
        tests_summary = ai.run_test_gen(
            project_root=proj,
            reports=reports,
            targets=targets,
            cfg=cfg,
            include_paths=inc_paths,
            defines=all_defines,
            progress_callback=progress_callback,
            agent_settings=agent_settings,
            rag_kb=kb,
        )
        if "enabled" not in tests_summary:
            tests_summary["enabled"] = True

        # P2.1: AI 생성 테스트를 CTest 실행 대상으로 자동 등록
        cm_info = {"generated": False, "reason": "review_mode"}
        if tests_summary.get("mode") != "review":
            cm_info = _generate_auto_generated_cmakelists(
                project_root=proj,
                reports=reports,
                tests_summary=tests_summary,
                include_paths=inc_paths,
                defines=all_defines,
                stubs_root=stubs_root,
            )
        tests_summary["cmake"] = cm_info

    # 4. [Step 3] Build & Test
    b_res = common.standardize_result(False, "skipped")
    coverage_summary: Dict[str, Any] = {
        "enabled": False,
        "ok": False,
        "line_rate": None,
        "threshold": None,
        "below_threshold": False,
        "xml": None,
        "html": None,
    }

    if do_build_and_test or do_clang_tidy:
        asan_msg = " (with ASan)" if do_asan else ""
        common.log_msg(log_callback, f"🏗️ [Step 3] CMake Build & Test{asan_msg}...")

        _check_stop()
        b_res = build.build_and_tests(proj, reports, do_coverage, do_asan)

        # P2.1: CTest 결과를 tests 섹션에도 pass/fail로 재집계
        try:
            _attach_ai_test_execution_to_summary(tests_summary, b_res)
        except Exception:
            pass

        # Fast-fail: 빌드 실패 시 후속 단계 단축(에이전트 미사용일 때)
        if fast_fail and (not agent_enabled_effective) and (not b_res.get("ok")):
            do_coverage = False
            do_fuzz = False
            do_qemu = False
            do_docs = False
            enable_domain_tests = False

        # Coverage report + threshold 계산
        if do_coverage and b_res.get("data", {}).get("build_ok", b_res.get("ok")):
            common.log_msg(log_callback, "📈 [Step 4] Generating Coverage Report (gcovr)...")
            try:
                cov_res = tools.generate_coverage_report(
                    proj, reports, Path(b_res["data"]["build_dir"])
                )
            except Exception as e:
                cov_res = {"ok": False, "reason": "coverage_exception", "error": str(e)}

            coverage_summary["enabled"] = True
            coverage_summary["ok"] = cov_res.get("ok", False)
            coverage_summary["xml"] = cov_res.get("xml")
            coverage_summary["html"] = cov_res.get("html")

            cov_threshold = getattr(config, "DEFAULT_COVERAGE_THRESHOLD", 0.0)
            env_thr = os.environ.get("COVERAGE_THRESHOLD")
            if env_thr is not None:
                try:
                    cov_threshold = float(env_thr)
                except ValueError:
                    pass
            coverage_summary["threshold"] = cov_threshold or 0.0

            if cov_res.get("ok") and cov_res.get("xml"):
                try:
                    tree = ET.parse(cov_res["xml"])
                    root = tree.getroot()
                    line_rate_attr = root.attrib.get("line-rate")
                    if line_rate_attr is not None:
                        line_rate = float(line_rate_attr)
                        coverage_summary["line_rate"] = line_rate
                        coverage_summary["line_rate_pct"] = line_rate * 100.0
                        if cov_threshold and line_rate < cov_threshold:
                            coverage_summary["below_threshold"] = True
                except Exception as e:
                    coverage_summary["parse_error"] = str(e)

    # 5. [Step 5] AI Fuzzing
    fuzz_res: Dict[str, Any] = {"enabled": False, "ok": True, "results": [], "reason": "skipped"}
    if do_fuzz and cfg:
        runtime_targets = _pick_runtime_targets(targets, all_targets)
        if not runtime_targets:
            fuzz_res = {"enabled": True, "ok": True, "results": [], "reason": "no_targets"}
        elif not _has_libfuzzer_runtime():
            # 현재 컨테이너에 compiler-rt가 없는 경우를 명시적으로 기록
            if fuzz_strict:
                common.log_msg(
                    log_callback,
                    "❌ LibFuzzer/ASan clang runtime missing → fuzzing requested but cannot run (strict mode).\n"
                    "   (clang / llvm / compiler-rt 패키지 설치 여부 점검 필요)",
                )
                fuzz_res = {"enabled": True, "ok": False, "results": [], "reason": "libfuzzer_runtime_missing"}
            else:
                common.log_msg(
                    log_callback,
                    "⚠️ LibFuzzer/ASan clang runtime missing → skipping fuzzing step.\n"
                    "   (예: clang / llvm / compiler-rt 패키지가 설치되어 있는지 확인)",
                )
                fuzz_res = {"enabled": True, "ok": True, "results": [], "reason": "libfuzzer_runtime_missing"}
        else:
            common.log_msg(log_callback, "💣 [Step 5] Running AI Fuzzing...")

            fuzz_inc_paths = (
                inc_paths
                + tools.get_arch_include_paths(target_arch, str(proj))
            )

            fuzz_default = getattr(config, "FUZZ_DEFAULT_DURATION", 10)
            fuzz_focus = getattr(
                config,
                "FUZZ_FOCUS_DURATION",
                max(fuzz_default, 30),
            )
            fuzz_keywords: List[str] = getattr(
                config,
                "FUZZ_FOCUS_KEYWORDS",
                ["e2e", "gateway", "protocol", "parser"],
            )
            max_focus = getattr(config, "FUZZ_MAX_FOCUS_TARGETS", 3)
            max_total = getattr(config, "FUZZ_MAX_TOTAL_TARGETS", len(runtime_targets))

            focus_candidates = [
                t for t in runtime_targets if any(k in t.name.lower() for k in fuzz_keywords)
            ]
            focus_targets = focus_candidates[:max_focus]

            remaining = [t for t in runtime_targets if t not in focus_targets]
            other_budget = max(0, max_total - len(focus_targets))
            other_targets = remaining[:other_budget]

            work_dir = reports / "fuzz"
            tools.ensure_dir(work_dir)

            total = len(focus_targets) + len(other_targets)
            idx = 0

            for t in focus_targets:
                if progress_callback:
                    progress_callback(idx, total, f"Fuzzing (focus) {t.name}")
                try:
                    harness = work_dir / f"fuzz_{t.stem}_harness.c"
                    _write_fuzz_harness(harness, t)
                    
                    stubs_dir = (proj / stubs_root).resolve() if stubs_root else (proj / "tests" / "stubs").resolve()
                    incs = [str(stubs_dir)] + [
                        str(Path(p).resolve())
                        for p in fuzz_inc_paths
                        if str(p).strip() and str(Path(p).resolve()) != str(stubs_dir)
                    ]
                    
                    res = tools.run_libfuzzer(
                        harness_path=harness,
                        source_files=[t],
                        include_dirs=incs,
                        work_dir=work_dir,
                        duration_sec=fuzz_focus,
                        artifact_prefix=f"fuzz_{t.stem}",
                    )
                except Exception as e:
                    res = {"ok": False, "crash_found": False, "error": str(e)}

                res.update({"target": t.name, "focus": True, "duration": fuzz_focus})
                fuzz_res["results"].append(res)
                status = "ERROR" if not res.get("ok", True) else ("CRASH" if res.get("crash_found") else "PASS")
                common.log_msg(
                    log_callback,
                    f"   - Fuzz (focus) {t.name} [{fuzz_focus}s]: {status}",
                )
                idx += 1

            for t in other_targets:
                if progress_callback:
                    progress_callback(idx, total, f"Fuzzing {t.name}")
                try:
                    harness = work_dir / f"fuzz_{t.stem}_harness.c"
                    _write_fuzz_harness(harness, t)
                    
                    stubs_dir = (proj / stubs_root).resolve() if stubs_root else (proj / "tests" / "stubs").resolve()
                    incs = [str(stubs_dir)] + [
                        str(Path(p).resolve())
                        for p in fuzz_inc_paths
                        if str(p).strip() and str(Path(p).resolve()) != str(stubs_dir)
                    ]
                    
                    res = tools.run_libfuzzer(
                        harness_path=harness,
                        source_files=[t],
                        include_dirs=incs,
                        work_dir=work_dir,
                        duration_sec=fuzz_default,
                        artifact_prefix=f"fuzz_{t.stem}",
                    )
                except Exception as e:
                    res = {"ok": False, "crash_found": False, "error": str(e)}

                res.update({"target": t.name, "focus": False, "duration": fuzz_default})
                fuzz_res["results"].append(res)
                status = "ERROR" if not res.get("ok", True) else ("CRASH" if res.get("crash_found") else "PASS")
                common.log_msg(
                    log_callback,
                    f"   - Fuzz {t.name} [{fuzz_default}s]: {status}",
                )
                idx += 1

            fuzz_res["enabled"] = True
            fuzz_res["reason"] = "completed"
            fuzz_res["focus_keywords"] = fuzz_keywords
            fuzz_res["focus_count"] = len(focus_targets)

            # overall fuzz status
            fuzz_ok = True
            for r in fuzz_res.get("results", []):
                if not r.get("ok", True) or r.get("crash_found"):
                    fuzz_ok = False
                    break
            fuzz_res["ok"] = fuzz_ok

    # 6. [Step 6] QEMU Smoke / Sanity Test
    qemu_res: Dict[str, Any] = {"enabled": False, "ok": False, "reason": "skipped"}
    if do_qemu:
        common.log_msg(log_callback, "🖥️ [Step 6] Running QEMU Smoke Test...")

        build_dir = None
        if b_res.get("ok") and b_res.get("data", {}).get("build_dir"):
            try:
                build_dir = Path(b_res["data"]["build_dir"])
            except Exception:
                build_dir = None

        elf = _resolve_qemu_elf(proj, build_dir)
        if elf:
            common.log_msg(log_callback, f"       → Found ELF: {elf.name}")
            qemu_res = tools.run_qemu_smoke_test(
                elf,
                artifact_dir=reports / "qemu",
                artifact_prefix="qemu_smoke",
            )
            qemu_res["enabled"] = True
            qemu_res["effective_ok"] = qemu_res.get("ok", True)

            log_text = qemu_res.get("log", "") or ""
            patterns: List[str] = getattr(
                config,
                "QEMU_LOG_ERROR_PATTERNS",
                ["HardFault", "ASSERT", "panic", "Segmentation fault"],
            )
            
            # [NEW] RP2040 check for warning instead of error
            is_rp2040 = ("rp2040" in target_arch.lower()) or ("cortex-m0plus" in target_arch.lower())

            if log_text and any(p in log_text for p in patterns):
                qemu_res["ok"] = False
                qemu_res["reason"] = "runtime_error_pattern_in_log"
                qemu_res["effective_ok"] = False

            soft_fail = bool(is_rp2040 and qemu_res.get("reason") == "runtime_error_pattern_in_log")
            if soft_fail:
                qemu_res["effective_ok"] = True
                qemu_res["soft_fail"] = True

            if not qemu_res.get("ok"):
                if soft_fail:
                    status = "WARN (RP2040 Soft-Fail)"
                    common.log_msg(log_callback, f"   ⚠️ QEMU {status}")
                else:
                    status = "FAIL"
                    common.log_msg(log_callback, f"   - QEMU Emulation: {status}")
            else:
                status = "PASS"
                common.log_msg(log_callback, f"   - QEMU Emulation: {status}")
        else:
            common.log_msg(log_callback, "   - No ELF file found for QEMU.")
            qemu_res = {"enabled": True, "ok": False, "effective_ok": False, "reason": "no_elf"}

    if not do_qemu:
        common.log_msg(log_callback, "🖥️ [Step 6] QEMU Smoke Test skipped (do_qemu=False).")

    # 7. [Step 7] Documentation
    docs_res: Dict[str, Any] = {"enabled": False, "ok": False, "reason": "skipped"}
    if do_docs:
        common.log_msg(
            log_callback,
            "📚 [Step 7] Generating Documentation (Doxygen)...",
        )
        try:
            tools.run_doxygen(proj, reports / "docs")
            docs_res.update({"enabled": True, "ok": True, "reason": "completed"})
        except Exception as e:
            docs_res.update({"enabled": True, "ok": False, "reason": f"doxygen_failed: {e}"})
            common.log_msg(log_callback, f"   ⚠️ Doxygen failed: {e}")
    else:
        common.log_msg(log_callback, "📚 [Step 7] Documentation skipped (do_docs=False).")
        docs_res["reason"] = "disabled"

    # 8. [Step 8] Syntax Check
    syn_res = common.standardize_result(True, "skipped")
    if do_syntax_check and targets:
        common.log_msg(log_callback, "🔍 [Step 8] Running Syntax Check...")
        _check_stop()
        syn_res = static.run_gcc_syntax(
            proj,
            reports,
            targets,
            inc_paths,
            all_defines,
            progress_callback,
            target_arch,
        )
        # [NEW] Enhanced failure logging
        if not syn_res.get("ok"):
            common.log_msg(log_callback, "   ❌ Syntax Check Failed on specific files:")
            for r in syn_res.get("data", {}).get("results", []):
                if not r.get("ok"):
                    # 첫 줄만 잘라서 보여주기
                    err_preview = (r.get("stderr", "") or "").strip().split("\n")[0][:100]
                    common.log_msg(log_callback, f"      - {r.get('file')}: {err_preview}")

    # 9. [Step 9] Static Analysis (Cppcheck)
    cpp_res = common.standardize_result(True, "skipped")
    if targets:
        common.log_msg(log_callback, "🔎 [Step 9] Running Cppcheck...")
        cpp_res = static.run_cppcheck(
            proj,
            reports,
            targets,
            cppcheck_enable,
            inc_paths,
            suppressions_path,
            progress_callback,
            target_arch,
            all_defines,
        )

    # 10. [Step 10] Clang-Tidy
    tidy_res = common.standardize_result(True, "skipped")
    if do_clang_tidy and targets and b_res.get("ok"):
        common.log_msg(log_callback, "🧹 [Step 10] Running Clang-Tidy...")
        tidy_res = static.run_clang_tidy(
            proj,
            targets,
            clang_tidy_checks or [],
            Path(b_res["data"]["build_dir"]),
            progress_callback,
        )

    # 11. [Step 11] Domain Test Panel
    domain_tests_summary: Dict[str, Any] = {
        "enabled": False,
        "tests": [],
        "errors": [],
        "reason": "skipped",
    }
    if enable_domain_tests and cfg:
        common.log_msg(
            log_callback,
            "🧪 [Step 11] Running Domain Test Panel...",
        )

        if domain_targets:
            dt_targets: List[str] = domain_targets
        else:
            dt_targets = []
            source_targets = _pick_runtime_targets(targets, all_targets)

            for t in source_targets:
                name = t.name.lower()
                if any(key in name for key in ("e2e", "gateway", "protocol", "lin")):
                    try:
                        rel = t.relative_to(proj)
                        dt_targets.append(str(rel))
                    except ValueError:
                        dt_targets.append(str(t))

        if dt_targets:
            dt_cfg = DomainTestConfig(
                language="c",
                test_framework="assert",
                max_scenarios_per_file=8,
            )

            logs_dir = reports / "agent_logs" / "domain_tests"

            def _llm(messages: List[Dict[str, str]]) -> str:
                reply = ai.agent_call_text(
                    cfg,
                    messages,
                    logs_dir,
                    role="generator",
                    stage="domain_tests",
                    rag_kb=kb,
                    rag_query=(messages[-1].get("content", "") if messages else ""),
                    settings=agent_settings,
                )
                return reply or ""

            domain_res = run_domain_test_panel(
                project_root=proj,
                targets=dt_targets,
                llm_call=_llm,
                config=dt_cfg,
                output_dir=proj / "tests" / "domain",
                domain_notes=(
                    "Embedded C project. If this is an automotive LIN gateway, "
                    "focus on E2E counters, CRC, invalid frames, and timeout behavior."
                ),
            )
            domain_tests_summary = {**domain_res, "enabled": True, "reason": "completed"}
        else:
            common.log_msg(
                log_callback,
                "ℹ️ Domain Test Panel: no matching targets, skipped.",
            )
            domain_tests_summary["reason"] = "no_matching_targets"

    elif enable_domain_tests and not cfg:
        common.log_msg(
            log_callback,
            "🧪 [Step 11] Domain Test Panel skipped (missing LLM config).",
        )
        domain_tests_summary["reason"] = "missing_llm_config"
    else:
        common.log_msg(
            log_callback,
            "🧪 [Step 11] Domain Test Panel skipped (enable_domain_tests=False).",
        )
        domain_tests_summary["reason"] = "disabled"

    # 12. [Step 12] AI Agent Loop
    agent_res: Dict[str, Any] = {
        "iterations": 0,
        "applied_changes": [],
        "stop_reason": "none",
        "history": [],
        "patch_mode": effective_patch_mode,
        "patch_files": [],
    }

    if (
        agent_enabled_effective
        and cfg
        and effective_patch_mode != "off"
        and (targets or not b_res.get("ok"))
    ):
        common.log_msg(
            log_callback,
            "🤖 [Step 12] Starting AI Self-Healing Loop...",
        )

        for i in range(max_iterations):
            _check_stop()
            current_iter = i + 1
            issues: List[Dict[str, Any]] = []
            fix_mode = "static"
            prompt = ""
            error_context_for_rag = ""

            if b_res["reason"] != "skipped" and not b_res.get("ok"):
                fix_mode = "build_fix"
                ctx = _build_ai_context_for_build_failure(proj, b_res, max_chars=ai_log_max_chars)
                error_context_for_rag = ctx.get("rag_key", "")

                issues = [{"file": "BUILD_LOG", "line": 0, "message": "Build Failed", "id": "build_error"}]
                prompt = (
                    "Build/Test failed. Use the context below to fix the root cause.\n"
                    "If unit tests failed, prioritize fixing production code first (libs/).\n"
                    "If host build is missing headers, prefer adding/adjusting stubs under tests/stubs or guarding includes properly.\n\n"
                    f"Build Context:\n{ctx.get('context', '')}\n"
                )
            elif syn_res and not syn_res.get("ok"):
                fix_mode = "syntax_fix"
                fails = [r for r in syn_res["data"]["results"] if not r.get("ok", True)]
                if fails:
                    error_context_for_rag = (fails[0].get("stderr", "") or "")[:300]
                    issues = [{"file": r["file"], "line": 0, "message": r.get("stderr", "")} for r in fails]

            else:
                cpp_issues = cpp_res.get("data", {}).get("issues", [])
                tidy_issues = tidy_res.get("data", {}).get("issues", [])
                issues = cpp_issues + tidy_issues
                if issues:
                    error_context_for_rag = issues[0].get("message", "")

            if not issues:
                agent_res["stop_reason"] = "clean"
                common.log_msg(log_callback, "🎉 Code is clean! No issues to fix.")
                break

            common.log_msg(
                log_callback,
                f"   ▶ Iter {current_iter}: Fixing {len(issues)} issues [{fix_mode}]...",
            )

            roles_enabled = {str(r).lower() for r in (agent_settings.get("roles") or [])}

            past_solutions: List[Dict[str, Any]] = []
            rag_context = ""
            if agent_settings.get("rag_enabled"):
                past_solutions = kb.search(
                    error_context_for_rag,
                    role="fixer",
                    stage=fix_mode,
                    tags=["fixer", fix_mode],
                )
                if past_solutions:
                    common.log_msg(
                        log_callback,
                        f"      📚 Found {len(past_solutions)} RAG solutions!",
                    )
                    rag_context = "\n\n[📚 Knowledge Base - Past Successful Fixes]:\n"
                    for idx, sol in enumerate(past_solutions):
                        score = sol.get("score", 0.0)
                        rag_context += f"--- Example {idx + 1} (Score: {score:.2f}) ---\n"
                        rag_context += f"Error: {sol.get('error_clean', '')[:100]}...\n"
                        rag_context += "Fix Pattern:\n"
                        rag_context += f"{sol.get('fix', '')}\n"

            planner_notes = ""
            if "planner" in roles_enabled:
                planner_prompt = (
                    "Create a short fix plan (bullets, max 6). "
                    "Focus on root cause and safest edits.\n\n"
                    f"Issues:\n{json.dumps(issues[:5], indent=2)}\n"
                )
                if prompt:
                    planner_prompt += f"\nContext:\n{prompt}\n"
                planner_messages = [{"role": "user", "content": planner_prompt}]
                planner_notes = ai.agent_call_text(
                    cfg,
                    planner_messages,
                    reports / "agent_logs",
                    role="planner",
                    stage=fix_mode,
                    task_id=f"planner_iter{current_iter}",
                    rag_kb=kb,
                    rag_query=error_context_for_rag,
                    settings=agent_settings,
                ) or ""
                if planner_notes:
                    prompt = f"{prompt}\n\nPlanner Notes:\n{planner_notes}\n"

            if fix_mode != "build_fix":
                max_findings = getattr(config, "MAX_FINDINGS_FOR_PROMPT", 5)
                top_issues = issues[:max_findings]
                excerpts = {
                    item["file"]: common.read_excerpt(proj / item["file"])
                    for item in top_issues
                    if item.get("file")
                }
                prompt = (
                    "Fix these code issues:\n"
                    f"{json.dumps(top_issues, indent=2)}\n\n"
                    "Source Code Context:\n"
                    f"{json.dumps(excerpts, indent=2)}\n"
                )

            full_prompt = (
                f"{prompt}\n{rag_context}\n\n"
                "Task: Output ONLY SEARCH/REPLACE blocks to fix these issues.\n"
                "Format:\n"
                "<<<<SEARCH_BLOCK[filename]...\n"
                "<<<<REPLACE_BLOCK[filename]..."
            )

            messages = [{"role": "user", "content": full_prompt}]

            def _validate_patch(reply_text: str) -> Tuple[bool, str]:
                try:
                    blocks = ai._parse_search_replace_blocks(reply_text)
                    if blocks:
                        return True, ""
                    return False, "no_search_replace_blocks"
                except Exception as e:
                    return False, f"parse_error: {e}"

            # P2.2: LLM ??? ?? ?? (???2?+ fallback + ?? ??)
            total_attempts = int(getattr(config, "AGENT_LLM_TOTAL_ATTEMPTS", 3))
            fallback_models = _csv_list(getattr(config, "AGENT_LLM_FALLBACK_MODELS", ""))
            fallback_cfg_paths = _csv_list(getattr(config, "AGENT_LLM_FALLBACK_CONFIGS", ""))
            llm_attempts: List[Dict[str, Any]] = []

            def _policy_call(msgs: List[Dict[str, str]]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
                reply, attempts_meta = _llm_call_with_policy(
                    cfg_primary=cfg,
                    cfg_fallbacks=cfg_fallbacks,
                    messages=msgs,
                    log_dir=reports / "agent_logs",
                    total_attempts=total_attempts,
                    fallback_models=fallback_models,
                    fallback_config_paths=fallback_cfg_paths,
                    stage=fix_mode,
                )
                gemini_content = None
                if isinstance(attempts_meta, list):
                    for ent in reversed(attempts_meta):
                        if isinstance(ent, dict) and "gemini_content" in ent:
                            gemini_content = ent.get("gemini_content")
                            break
                    for ent in attempts_meta:
                        if isinstance(ent, dict) and "gemini_content" in ent:
                            ent["gemini_content"] = True
                llm_attempts[:] = attempts_meta
                return reply, {"attempts": attempts_meta, "gemini_content": gemini_content}

            fixer_res = ai.agent_call(
                cfg,
                messages,
                reports / "agent_logs",
                role="fixer",
                stage=fix_mode,
                task_id=f"fixer_iter{current_iter}",
                rag_kb=kb,
                rag_query=error_context_for_rag,
                settings=agent_settings,
                validator=_validate_patch,
                llm_call_fn=_policy_call,
            )
            reply = fixer_res.get("output")

            # Plan B: RAG ?? ???? LLM ????? RAG fix pattern?? ?? ??
            plan_b = None
            if not reply and past_solutions:
                best = _pick_best_rag_solution(past_solutions)
                max_blocks = int(getattr(config, "AGENT_RAG_PLANB_MAX_BLOCKS", 3))
                plan_text = _extract_search_replace_blocks_text((best or {}).get("fix", ""), max_blocks)
                if plan_text:
                    plan_b = {
                        "used": True,
                        "source": "rag",
                        "id": (best or {}).get("id"),
                        "score": (best or {}).get("score"),
                        "max_blocks": max_blocks,
                    }
                    reply = plan_text
                    common.log_msg(log_callback, "🧯 Plan B: Applying RAG-based rule patch (limited blocks).")

            agent_res.setdefault("history", []).append(
                {
                    "iter": current_iter,
                    "fix_mode": fix_mode,
                    "issue_count": len(issues),
                    "planner": {"used": bool(planner_notes), "notes_preview": planner_notes[:500]},
                    "fixer": {
                        "final_ok": bool(reply),
                        "llm_attempts": llm_attempts,
                        "plan_b": plan_b,
                    },
                }
            )

            if not reply:
                agent_res["stop_reason"] = "no_llm_response"
                common.log_msg(log_callback, "⚠️ No response from AI (after retries/fallback).")
                break

            if effective_patch_mode == "review":
                patch_path = _save_agent_patch(
                    reports,
                    reply,
                    current_iter,
                    fix_mode,
                )
                agent_res["patch_files"].append(str(patch_path))
                agent_res["iterations"] = current_iter
                agent_res["stop_reason"] = "review_pending"
                common.log_msg(
                    log_callback,
                    f"      📝 Saved AI suggestions to {patch_path} (review mode, no code modified).",
                )
                break

            changes = ai.apply_search_replace(
                proj,
                reply,
                reports / "agent_logs",
            )
            applied_patches = [c for c in changes if c.get("status") == "ok"]
            agent_res["applied_changes"].extend(applied_patches)
            agent_res["iterations"] = current_iter

            if not applied_patches:
                agent_res["stop_reason"] = "patch_failed"
                common.log_msg(
                    log_callback,
                    "⚠️ AI suggested fixes could not be applied (Pattern mismatch).",
                )
                break

            for p in applied_patches:
                common.log_msg(log_callback, f"      ✅ Patched: {p['file']}")

            success = False
            if fix_mode == "build_fix":
                common.log_msg(
                    log_callback,
                    "      🔄 Re-running Build to verify fix...",
                )
                b_res = build.build_and_tests(
                    proj,
                    reports,
                    do_coverage,
                    do_asan,
                )
                success = b_res.get("ok")

            elif fix_mode == "syntax_fix":
                common.log_msg(
                    log_callback,
                    "      🔄 Re-running Syntax Check...",
                )
                syn_res = static.run_gcc_syntax(
                    proj,
                    reports,
                    targets,
                    inc_paths,
                    all_defines,
                    None,
                    target_arch,
                )
                success = syn_res.get("ok")

            else:
                common.log_msg(
                    log_callback,
                    "      🔄 Re-running Static Analysis...",
                )
                check_res = static.run_gcc_syntax(
                    proj,
                    reports,
                    targets,
                    inc_paths,
                    all_defines,
                    None,
                    target_arch,
                )
                success = check_res.get("ok")
                if success:
                    cpp_res = static.run_cppcheck(
                        proj,
                        reports,
                        targets,
                        cppcheck_enable,
                        inc_paths,
                        suppressions_path,
                        None,
                        target_arch,
                        all_defines,
                    )

            if success:
                kb.learn(
                    error_context_for_rag,
                    reply[:2000],
                    tags=[fix_mode],
                    role="fixer",
                    stage=fix_mode,
                    context=error_context_for_rag,
                )
                common.log_msg(
                    log_callback,
                    "      🧠 Knowledge Base Updated: Solution learned!",
                )
            else:
                common.log_msg(
                    log_callback,
                    "      ❌ Fix did not resolve the issue fully.",
                )

    elif enable_agent and effective_patch_mode == "off":
        agent_res["stop_reason"] = "patch_mode_off"
        common.log_msg(
            log_callback,
            "🤖 Agent enabled but patch mode is 'off' → skipping self-healing loop.",
        )

    else:
        if not enable_agent:
            agent_res["stop_reason"] = "agent_disabled"
            common.log_msg(
                log_callback,
                "🤖 [Step 12] Agent loop skipped (enable_agent=False).",
            )
        elif not cfg:
            agent_res["stop_reason"] = "missing_llm_config"
            common.log_msg(
                log_callback,
                "🤖 [Step 12] Agent loop skipped (missing LLM config).",
            )
        elif not (targets or not b_res.get("ok")):
            agent_res["stop_reason"] = "no_targets"
            common.log_msg(
                log_callback,
                "🤖 [Step 12] Agent loop skipped (no targets and build OK).",
            )

    # 15. Final Summary & Exit Code
    exit_code = 0
    failure_stage = "none"

    static_issue_count = (
        len(cpp_res.get("data", {}).get("issues", []))
        + len(tidy_res.get("data", {}).get("issues", []))
    )

    coverage_below = (
        coverage_summary.get("enabled")
        and coverage_summary.get("below_threshold")
    )


    # strict gating for runtime steps (optional)
    fuzz_failed = bool(do_fuzz and fuzz_res.get("enabled") and (not fuzz_res.get("ok", True)) and bool(fuzz_strict))
    qemu_failed = bool(do_qemu and qemu_res.get("enabled") and (not qemu_res.get("effective_ok", qemu_res.get("ok", True))) and bool(qemu_strict))
    domain_failed = bool(
        enable_domain_tests
        and domain_tests_summary.get("enabled")
        and (not domain_tests_summary.get("ok", True))
        and bool(domain_tests_strict)
    )
    if not b_res.get("ok") and b_res["reason"] != "skipped":
        # Build 단계 실패와 Unit Test 실패를 구분
        b_reason = b_res.get("reason", "")
        b_data = b_res.get("data", {})
        if b_reason == "test_fail" or (b_data.get("build_ok") and not b_data.get("tests_ok", True)):
            exit_code = 2
            failure_stage = "unit_tests"
        else:
            exit_code = 2
            failure_stage = "build"
    elif not syn_res.get("ok"):
        exit_code = 3
        failure_stage = "syntax"
    elif static_issue_count > 0:
        if ignore_static_failure:
            exit_code = 0
            failure_stage = "static_issues_ignored"
        else:
            exit_code = 1
            failure_stage = "static_issues"
    elif coverage_below:
        exit_code = 1
        failure_stage = "coverage"

    elif static_issue_count == 0 and not coverage_below:
        if fuzz_failed:
            exit_code = 1
            failure_stage = "fuzz"
        elif qemu_failed:
            exit_code = 1
            failure_stage = "qemu"
        elif domain_failed:
            exit_code = 1
            failure_stage = "domain_tests"

    agent_runs: List[Dict[str, Any]] = []
    if isinstance(tests_summary, dict):
        ar = tests_summary.get("agent_runs")
        if isinstance(ar, list):
            agent_runs.extend(ar)

    summary: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "project_root": str(proj),
        "targets": [str(t) for t in targets],
        "static": {
            "cppcheck": cpp_res,
            "clang_tidy": tidy_res,
        },
        "build": b_res,
        "syntax": syn_res,
        "agent": agent_res,
        "agent_config": agent_settings,
        "agent_runs": agent_runs,
        "tests": tests_summary,
        "fuzzing": fuzz_res,
        "qemu": qemu_res,
        "coverage": coverage_summary,
        "docs": docs_res,
        "domain_tests": domain_tests_summary,
        "exit_code": exit_code,
        "failure_stage": failure_stage,
        "change_mode": change_mode,
        "engine_version": getattr(config, "ENGINE_VERSION", "unknown"),

        "strict": {
            "ci_env": ci_env,
            "fuzz_strict": bool(fuzz_strict),
            "qemu_strict": bool(qemu_strict),
            "domain_tests_strict": bool(domain_tests_strict),
        },
    }

    _write_json(reports / "analysis_summary.json", summary)

    flat_issues = cpp_res.get("data", {}).get("issues", []) + tidy_res.get("data", {}).get(
        "issues", []
    )
    _write_json(reports / "findings_flat.json", flat_issues)

    common.log_msg(log_callback, f"✅ Pipeline Finished. Exit Code: {exit_code}")
    return exit_code
