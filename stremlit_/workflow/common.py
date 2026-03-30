# /app/workflow/common.py
# -*- coding: utf-8 -*-
# Common Utilities for DevOps Workflow (v30.2: Safety Enhanced)

import shutil
import glob
import os
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable
import analysis_tools as tools

class PipelineStopRequested(Exception):
    """GUI/CLI에서 사용자가 중단을 요청했을 때 발생"""
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
        except Exception:
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
    GUI의 실시간 로그 창과 연동됩니다.
    """
    if callback:
        callback(msg)
    else:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [{level.upper()}] {msg}")

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
    except Exception as e:
        print(f"[WARN] Failed to create backup for {file_path}: {e}")
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
            print(f"♻️ Restored original file: {file_path.name}")
            return True
        except Exception as e:
            print(f"[ERR] Failed to restore {file_path}: {e}")
    return False

def normalize_whitespace(s: str) -> str:
    """문자열의 공백을 정규화합니다."""
    return " ".join(s.split())

def read_excerpt(p: Path, max_lines: int = 120) -> str:
    """파일의 내용을 읽어오되, 너무 길면 앞부분만 잘라서 반환합니다."""
    try: 
        return "\n".join(p.read_text(encoding="utf-8", errors="ignore").splitlines()[:max_lines])
    except: 
        return ""

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

def get_git_changed_files(project_root: Path) -> Tuple[List[Path], str]:
    """
    Git 저장소일 경우 변경된 파일 목록만 추출합니다 (Incremental Analysis).
    """
    changed = []
    if not tools.which("git"): 
        return [], "git_missing"
        
    # Git 저장소인지 확인
    c, out, _ = tools.run_command(["git", "rev-parse", "--is-inside-work-tree"], cwd=project_root)
    if c != 0 or out.strip() != "true": 
        return [], "not_git_repo"
    
    mode = "git_ok"
    # 1. Staged + Unstaged 변경 사항 확인
    cmds = [
        ["git", "diff", "--name-only", "HEAD"], 
        ["git", "ls-files", "--others", "--exclude-standard"] # Untracked files
    ]
    
    for cmd in cmds:
        c, out, err = tools.run_command(cmd, cwd=project_root)
        if c == 0:
            for l in out.splitlines():
                if l.strip(): 
                    full_path = (project_root / l.strip()).resolve()
                    if full_path.exists():
                        changed.append(full_path)
        else:
            # HEAD가 없는 경우 (첫 커밋 전) 등 에러 처리
            if "HEAD" in str(cmd) and "no such ref" in (err or "").lower(): 
                mode = "no_head"
            elif mode == "git_ok": 
                mode = "error"
                
    return list(set(changed)), mode

def check_llm_connection(config_path: str) -> Tuple[bool, str]:
    """LLM 서버(Ollama) 연결 상태를 확인합니다."""
    import requests, json
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
