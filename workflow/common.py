# /app/workflow/common.py
# -*- coding: utf-8 -*-
# Common Utilities for DevOps Workflow (v30.2: Safety Enhanced)

import glob
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import analysis_tools as tools
from utils.log import get_logger

_logger = get_logger(__name__)

class PipelineStopRequested(Exception):
    """UI/CLI에서 사용자가 중단을 요청했을 때 발생"""
    pass


def check_stop(stop_check: Optional[Callable[[], None]] = None, stop_flag: Optional[Path] = None) -> None:
    """stop_check 콜백 또는 stop_flag 파일 존재로 중지 여부 확인"""
    if stop_check is not None:
        stop_check()
    if stop_flag is not None:
        try:
            if Path(stop_flag).exists():
                raise PipelineStopRequested("Stop flag detected")
        except PipelineStopRequested:
            raise
        except OSError:
            pass


@dataclass
class Issue:
    file: str
    line: int
    severity: str
    message: str
    id: str
    tool: str = "cppcheck"
    cwe: Optional[str] = None

def log_msg(callback: Optional[Callable[[str], None]], msg: str, level: str = "info"):
    """
    로그 메시지를 출력하거나 콜백으로 전달합니다.
    UI의 실시간 로그 창과 연동됩니다.
    """
    if callback:
        callback(msg)
    else:
        log_fn = getattr(_logger, level.lower(), _logger.info)
        log_fn("%s", msg)


def append_run_header(log_path: Path, title: str) -> None:
    """로그 파일에 런 헤더를 추가합니다."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n----- {title} -----\n")
    except OSError:
        pass


def make_tee_logger(callback: Optional[Callable[[str], None]], log_path: Path) -> Callable[[str], None]:
    """메시지를 파일에 저장하면서 기존 콜백에도 전달하는 로거."""
    def _logger(msg: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        if callback:
            callback(msg)
        else:
            _logger.info("%s", msg)
    return _logger

def standardize_result(ok: bool, reason: str = "", data: Any = None) -> Dict[str, Any]:
    """분석 결과를 표준화된 딕셔너리 형태로 반환합니다."""
    return {
        "ok": ok, 
        "reason": reason, 
        "data": data or {}, 
        "timestamp": datetime.now().isoformat()
    }

def create_backup(file_path: Path) -> Optional[Path]:
    """
    파일 백업을 생성합니다 (.bak).
    주의: 이미 .bak 파일이 존재하면 덮어쓰지 않습니다 (최초 원본 보존).
    """
    backup_path = file_path.with_suffix(file_path.suffix + ".bak")
    try:
        if not backup_path.exists():
            shutil.copy2(file_path, backup_path)
            return backup_path
        # 이미 백업이 있으면 그게 '진짜 원본'이므로 유지함
        return backup_path
    except (PermissionError, OSError) as e:
        _logger.warning("Failed to create backup for %s: %s", file_path, e)
        return None

def restore_from_backup(file_path: Path) -> bool:
    """
    백업 파일(.bak)이 존재하면 원본 파일로 복구합니다.
    AI 자동 수정이 실패했을 때 호출될 수 있습니다.
    """
    backup_path = file_path.with_suffix(file_path.suffix + ".bak")
    if backup_path.exists():
        try:
            shutil.copy2(backup_path, file_path)
            _logger.info("Restored original file: %s", file_path.name)
            return True
        except (PermissionError, OSError) as e:
            _logger.error("Failed to restore %s: %s", file_path, e)
    return False

def normalize_whitespace(s: str) -> str:
    """문자열의 공백을 정규화합니다."""
    return " ".join(s.split())

def read_excerpt(p: Path, max_lines: int = 120) -> str:
    """파일의 내용을 읽어오되, 너무 길면 앞부분만 잘라서 반환합니다.

    ⚠ 실패하면 `""` 다 — 그리고 그 `""` 는 **AI 입력으로 그대로 간다**
      (`workflow/ai.py:2276·2310·3391`, `workflow/pipeline.py:1578·3268`). 즉 읽기가
      실패하면 "코드를 못 읽었다" 가 아니라 **코드가 비어 있다**는 뜻으로 전달된다.
      반환형을 바꾸면 소비처 5곳이 흔들리므로 계약은 그대로 둔다.

    ⚠ 예전엔 맨 `except:` 였다. 그건 `KeyboardInterrupt`·`SystemExit` 까지 삼켜
      파일 읽는 동안 Ctrl+C 가 안 먹는다. `Exception` 으로 좁히면 그 둘만 통과시키고
      **삼키는 범위는 그대로**다.

    ⚠ 2026-09-02 정정 — 직전 판은 "이 자리엔 OSError 아닌 실패도 실제로 난다"고 적고
      범위를 넓혀 뒀다. **틀렸다.** 근거였던 `pytest -n auto` 워커 사망(`ValueError:
      I/O operation on closed file`)은 이 except 와 무관했다. 계측으로 확인한 실측:

        · 삼킨 예외를 전량 기록하고 전체 스위트를 2회 — 기록된 건 **`FileNotFoundError`
          단 1건**(= OSError, `test_common.py::test_nonexistent` 의 의도된 것)
        · `except OSError` 와 **동일 동작**(비-OSError 는 재던지기)으로 전량 실행 —
          8,476 passed / exit 0, 워커 사망 없음

      즉 그때의 사망은 **스위트가 도는 동안 소스를 편집한 것**이 유력하다(저장소가 이미
      기록해 둔 거짓 실패 기전). 정체를 모르는 실패를 근거로 범위를 넓히면, 실재하지 않는
      결함을 지키느라 진짜 예외까지 계속 삼킨다.

    ⚠ 그래서 `OSError` 로 좁히되, 삼킨 것은 `_record_swallowed` 로 **관측 가능**하게 둔다
      (`ARIA_READ_EXCERPT_TRACE` 미설정이면 부담 0). 침묵을 없앨 수 없다면 최소한
      보이게는 해 둔다.  # silent-ok

    ⚠ `OSError` 가 아닌데 `read_text` 가 낼 수 있는 것이 하나 있다 — 경로에 NUL 이
      들어가면 `ValueError: embedded null character` 다(실측). **일부러 안 잡는다.**
      호출부 5곳은 정적분석기 출력(`_dedup_static_issues`)과 프로젝트 glob 에서 경로를
      만들어 실제로는 안 나오고(전체 스위트 2회 관측 0), 무엇보다 그건 **읽기 실패가
      아니라 경로가 망가진 것**이다. `""` 로 바꾸면 AI 에게 "코드가 비어 있다"는
      **틀린 사실**로 전달된다. 안 나는 경우를 위해 범위를 넓히는 건 바로 위에서
      틀렸다고 확인한 그 행동이다.
    """
    try:
        return "\n".join(p.read_text(encoding="utf-8", errors="ignore").splitlines()[:max_lines])
    except OSError as exc:
        _record_swallowed(p, exc)
        return ""


def _record_swallowed(p: Any, exc: BaseException) -> None:
    """`read_excerpt` 가 삼킨 예외를 기록한다 — **계측 전용, 동작 불변**.

    `ARIA_READ_EXCERPT_TRACE` 가 설정된 경우에만 그 경로(+`.<pid>`)에 append 한다.
    미설정이면 아무 일도 하지 않으므로 운영 경로 부담은 0 이다.

    왜 로거가 아니라 파일인가 — 이 자리에서 나는 실패의 유력 후보가
    `ValueError: I/O operation on closed file` 이다. 그런 상황에서 stdout/logger 로
    쓰면 **계측기 자신이 같은 실패로 죽어** 아무 기록도 안 남는다.

    ⚠ 계측기는 절대 본 흐름을 깨지 않는다 — 자기 실패는 삼킨다.
    """
    dest = os.environ.get("ARIA_READ_EXCERPT_TRACE") or ""
    if not dest:
        return
    try:
        import traceback
        with open(f"{dest}.{os.getpid()}", "a", encoding="utf-8", errors="replace") as fh:
            fh.write(f"=== {type(exc).__module__}.{type(exc).__name__}: {exc}\n")
            fh.write(f"    path={p!r}  type={type(p).__name__}\n")
            fh.write("-- 호출 스택 --" + chr(10))
            fh.write("".join(traceback.format_stack(limit=14)))
            fh.write("-- 예외 traceback --" + chr(10))
            fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            fh.write("\n")
    except Exception:
        pass   # silent-ok — 계측기가 본 흐름을 깨면 안 된다


def list_targets(project_root: Path, targets_glob: str) -> List[Path]:
    """
    분석 대상 파일 목록을 glob 패턴으로 찾습니다.
    특정 디렉토리(build, generated 등)는 자동으로 제외합니다.
    """
    patterns = [g.strip() for g in targets_glob.split(",") if g.strip()]
    files: List[Path] = []
    
    # 제외할 경로 키워드
    excludes = ["pico-sdk", "/Drivers/", "/CMSIS/", "/Middlewares/", "generated/", "build/", ".git/"]
    # 테스트/자동생성 소스는 기본적으로 정적분석 타깃에서 제외
    # 필요 시 DEVOPS_STATIC_INCLUDE_TESTS=1 로 포함 가능
    include_tests = os.environ.get("DEVOPS_STATIC_INCLUDE_TESTS", "0") == "1"
    if not include_tests:
        excludes += ["tests/", "reports/auto_generated/", "reports/build/"]
    
    for pattern in patterns:
        # Recursive globbing 지원
        for m in glob.glob(str(project_root / pattern), recursive=True):
            p = Path(m)
            if p.is_file():
                # 제외 경로 필터링
                if not any(ex in str(p).replace("\\", "/") for ex in excludes):
                    files.append(p)
                    
    # 중복 제거 후 절대 경로 리스트 반환
    return list(set([f.resolve() for f in files]))

def get_git_changed_items(project_root: Path, base_ref: Optional[str] = None) -> Tuple[List[Dict[str, str]], str, Optional[str]]:
    """
    Git 저장소일 경우 변경된 파일 목록만 추출합니다 (Incremental Analysis).
    """
    if not tools.which("git"):
        return [], "git_missing", None
        
    # Git 저장소인지 확인
    c, out, _ = tools.run_command(["git", "rev-parse", "--is-inside-work-tree"], cwd=project_root)
    if c != 0 or out.strip() != "true":
        return [], "not_git_repo", None
    
    mode = "git_ok"
    used_ref: Optional[str] = None
    # base_ref가 있으면 해당 ref 대비 변경 파일을 수집
    if base_ref:
        refs = [r.strip() for r in str(base_ref).replace("\n", ",").split(",") if r.strip()]
        for r in refs:
            c, _, _ = tools.run_command(["git", "rev-parse", "--verify", r], cwd=project_root)
            if c == 0:
                used_ref = r
                break
        if not used_ref:
            return [], "base_ref_invalid", None

    # 1. Staged + Unstaged 변경 사항 확인
    if used_ref:
        diff_cmd = ["git", "diff", "--name-status", f"{used_ref}...HEAD"]
    else:
        diff_cmd = ["git", "diff", "--name-status", "HEAD"]

    items: Dict[str, str] = {}
    c, out, err = tools.run_command(diff_cmd, cwd=project_root)
    if c == 0:
        for ln in (out or "").splitlines():
            parts = ln.split("\t")
            if not parts:
                continue
            status = parts[0].strip() if parts else ""
            path = parts[-1].strip() if parts else ""
            if not path:
                continue
            items[path] = status or "M"
    else:
        if "no such ref" in (err or "").lower():
            mode = "no_head"
        elif mode == "git_ok":
            mode = "error"

    # untracked
    c, out, _ = tools.run_command(["git", "ls-files", "--others", "--exclude-standard"], cwd=project_root)
    if c == 0:
        for l in (out or "").splitlines():
            p = l.strip()
            if p:
                items[p] = "?"

    out_items = [{"path": k, "status": v} for k, v in items.items()]
    return out_items, mode, used_ref


def get_git_changed_files(project_root: Path, base_ref: Optional[str] = None) -> Tuple[List[Path], str, Optional[str]]:
    items, mode, used_ref = get_git_changed_items(project_root, base_ref=base_ref)
    changed: List[Path] = []
    for it in items:
        p = str(it.get("path") or "")
        if not p:
            continue
        full_path = (project_root / p).resolve()
        if full_path.exists():
            changed.append(full_path)
    return list(set(changed)), mode, used_ref


def get_svn_changed_items(project_root: Path, base_ref: Optional[str] = None) -> Tuple[List[Dict[str, str]], str, Optional[str]]:
    """SVN 작업복사본 변경 파일 목록 (base_ref 지원)"""
    if not tools.which("svn"):
        return [], "svn_missing", None
    if not (project_root / ".svn").exists():
        return [], "not_svn_wc", None

    used_ref: Optional[str] = None
    if base_ref:
        used_ref = str(base_ref).strip()

    items: List[Dict[str, str]] = []
    if used_ref:
        if "://" in used_ref or used_ref.startswith(("svn+", "^/", "/")):
            cmd = ["svn", "diff", "--summarize", used_ref]
        else:
            cmd = ["svn", "diff", "--summarize", "-r", f"{used_ref}:HEAD"]
        c, out, _ = tools.run_command(cmd, cwd=project_root)
        if c != 0:
            return [], "svn_base_ref_invalid", None
        for line in (out or "").splitlines():
            if not line:
                continue
            status = line[0].strip()
            path = line[1:].strip()
            if not path:
                continue
            items.append({"path": path, "status": status or "M"})
    else:
        c, out, _ = tools.run_command(
            ["svn", "status", "--ignore-externals"],
            cwd=project_root,
        )
        if c != 0:
            return [], "svn_error", None
        for line in (out or "").splitlines():
            if not line:
                continue
            status = line[0]
            if status not in ("M", "A", "R", "C", "D", "!", "?"):
                continue
            rel = line[1:].strip()
            if rel:
                items.append({"path": rel, "status": status})

    return items, "svn_ok", used_ref


def get_svn_changed_files(project_root: Path, base_ref: Optional[str] = None) -> Tuple[List[Path], str, Optional[str]]:
    items, status, used_ref = get_svn_changed_items(project_root, base_ref=base_ref)
    changed: List[Path] = []
    for it in items:
        p = str(it.get("path") or "")
        if not p:
            continue
        full_path = (project_root / p).resolve()
        if full_path.exists():
            changed.append(full_path)
    return list(set(changed)), status, used_ref


def get_svn_meta(project_root: Path) -> Dict[str, Optional[str]]:
    """SVN 메타 정보 (url/revision/author/date/dirty)"""
    info: Dict[str, Optional[str]] = {
        "url": None,
        "revision": None,
        "author": None,
        "date": None,
        "dirty": None,
    }
    if not tools.which("svn"):
        return info
    if not (project_root / ".svn").exists():
        return info
    c, out, _ = tools.run_command(["svn", "info", "--show-item", "url"], cwd=project_root)
    if c == 0:
        info["url"] = out.strip() or None
    c, out, _ = tools.run_command(["svn", "info", "--show-item", "revision"], cwd=project_root)
    if c == 0:
        info["revision"] = out.strip() or None
    c, out, _ = tools.run_command(["svn", "info", "--show-item", "last-changed-author"], cwd=project_root)
    if c == 0:
        info["author"] = out.strip() or None
    c, out, _ = tools.run_command(["svn", "info", "--show-item", "last-changed-date"], cwd=project_root)
    if c == 0:
        info["date"] = out.strip() or None
    c, out, _ = tools.run_command(["svn", "status", "--short"], cwd=project_root)
    if c == 0:
        info["dirty"] = "DIRTY" if bool(out.strip()) else "CLEAN"
    return info


def get_git_meta(project_root: Path) -> Dict[str, Optional[str]]:
    """현재 Git 메타 정보 (branch/commit/dirty)"""
    info: Dict[str, Optional[str]] = {
        "branch": None,
        "commit": None,
        "dirty": None,
        "author": None,
        "message": None,
    }
    if not tools.which("git"):
        return info
    # Git repo인지 확인
    c, out, _ = tools.run_command(["git", "rev-parse", "--is-inside-work-tree"], cwd=project_root)
    if c != 0 or out.strip() != "true":
        return info
    # branch
    c, out, _ = tools.run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project_root)
    if c == 0:
        info["branch"] = out.strip() or None
    # commit (short)
    c, out, _ = tools.run_command(["git", "rev-parse", "--short", "HEAD"], cwd=project_root)
    if c == 0:
        info["commit"] = out.strip() or None
    # author / message
    c, out, _ = tools.run_command(["git", "log", "-1", "--pretty=format:%an"], cwd=project_root)
    if c == 0:
        info["author"] = out.strip() or None
    c, out, _ = tools.run_command(["git", "log", "-1", "--pretty=format:%s"], cwd=project_root)
    if c == 0:
        info["message"] = out.strip() or None
    # dirty
    c, out, _ = tools.run_command(["git", "status", "--porcelain"], cwd=project_root)
    if c == 0:
        info["dirty"] = "DIRTY" if bool(out.strip()) else "CLEAN"
    return info

def check_llm_connection(config_path: str) -> Tuple[bool, str]:
    """LLM 서버(Ollama) 연결 상태를 확인합니다."""
    import json

    import requests
    try:
        if Path(config_path).exists():
            cfg = json.loads(Path(config_path).read_text())
            cfg = cfg[0] if isinstance(cfg, list) else cfg
            base = cfg.get("base_url", "http://localhost:11434/v1")
            
            # 모델 목록 조회 API 호출
            resp = requests.get(base.rstrip("/") + "/models", timeout=3)
            if resp.status_code == 200:
                return (True, f"Connected to {base}")
            else:
                return (False, f"Error: {resp.status_code}")
    except Exception as e: 
        return False, str(e)
        
    return False, "Config not found"
