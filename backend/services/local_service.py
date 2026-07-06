from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

import config

from .paths import safe_resolve_under


_logger = logging.getLogger(__name__)


def _run_cmd(
    args: List[str],
    cwd: Path,
    timeout_sec: int = 900,
    stdin_input: Optional[str] = None,
) -> Tuple[int, str]:
    try:
        p = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            # Force UTF-8 decoding and replace undecodable bytes. Without this,
            # text=True falls back to the OS default (e.g. CP949 on Korean
            # Windows) and svn output containing localized error messages
            # raises UnicodeDecodeError inside subprocess — masking the real
            # return code.
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
            input=stdin_input,
        )
        out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
        return int(p.returncode), out.strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout expired"
    except Exception as exc:
        return 1, f"exception: {exc}"


# ── SVN feature detection ─────────────────────────────────────────────
# `svn --password-from-stdin` (Subversion 1.12+) lets us pipe the password
# via stdin instead of putting it on argv, where it would be visible via
# `ps`/Task Manager/audit logs. We cache the result per-process because
# `svn help checkout` is not free to run on every request.
_SVN_STDIN_SUPPORT_CACHE: Optional[bool] = None


def _svn_supports_password_stdin() -> bool:
    global _SVN_STDIN_SUPPORT_CACHE
    if _SVN_STDIN_SUPPORT_CACHE is not None:
        return _SVN_STDIN_SUPPORT_CACHE
    try:
        p = subprocess.run(
            ["svn", "help", "checkout"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        merged = (p.stdout or "") + "\n" + (p.stderr or "")
        support = "--password-from-stdin" in merged
    except FileNotFoundError:
        _logger.warning("svn binary not found on PATH; SCM checkout will fail")
        support = False
    except Exception as exc:
        _logger.warning("svn feature detection failed: %s", exc)
        support = False

    _SVN_STDIN_SUPPORT_CACHE = support
    if not support:
        _logger.warning(
            "subversion client does not support --password-from-stdin; "
            "passwords will be passed via argv and may be visible to other "
            "processes on this host. Upgrade subversion to >= 1.12 to suppress."
        )
    return support


def _sanitize_password(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (clean_password, error).

    Strip outer whitespace/newlines so the argv and stdin paths behave the
    same way. An embedded newline inside the value is treated as an error —
    svn's `--password-from-stdin` contract is "a single line", and most
    password embeddings are either the result of a pasted EOL by mistake or
    a deliberate injection attempt.
    """
    if raw is None:
        return "", None
    cleaned = str(raw).strip()
    if not cleaned:
        return "", None
    if "\n" in cleaned or "\r" in cleaned:
        return None, "password contains embedded newline — rejected"
    return cleaned, None


def run_git(
    *,
    project_root: str,
    workdir_rel: str,
    action: str,
    repo_url: str = "",
    branch: str = "",
    depth: int = 0,
    timeout_sec: int = 900,
) -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    workdir = safe_resolve_under(root, workdir_rel or ".")
    dest_rel = "."
    if action == "clone":
        dest_rel = workdir_rel or "."
    args: List[str] = ["git"]
    if action == "clone":
        if not repo_url:
            return {"rc": 1, "output": "repo_url required"}
        args += ["clone"]
        if branch.strip():
            args += ["--branch", branch.strip()]
        if int(depth) > 0:
            args += ["--depth", str(int(depth))]
        args += [repo_url.strip(), str(workdir)]
        rc, out = _run_cmd(args, cwd=root, timeout_sec=timeout_sec)
        return {"rc": rc, "output": out, "dest": str(workdir)}
    if action == "pull":
        args += ["pull", "--ff-only"]
    elif action == "fetch":
        args += ["fetch", "--all", "--prune"]
    elif action == "checkout":
        if not branch.strip():
            return {"rc": 1, "output": "branch required"}
        args += ["checkout", branch.strip()]
    else:
        return {"rc": 1, "output": "unknown action"}
    rc, out = _run_cmd(args, cwd=workdir, timeout_sec=timeout_sec)
    return {"rc": rc, "output": out, "dest": str(workdir)}


def run_svn(
    *,
    project_root: str,
    workdir_rel: str,
    action: str,
    repo_url: str = "",
    revision: str = "",
    username: str = "",
    password: str = "",
    timeout_sec: int = 900,
) -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    workdir = safe_resolve_under(root, workdir_rel or ".")
    args: List[str] = ["svn"]
    if action == "checkout":
        if not repo_url:
            return {"rc": 1, "output": "repo_url required"}
        clean_pw, pw_error = _sanitize_password(password)
        if pw_error:
            return {"rc": 1, "output": pw_error}
        args += ["checkout"]
        if revision.strip():
            args += ["-r", revision.strip()]
        if username.strip():
            args += ["--username", username.strip()]
        stdin_input: Optional[str] = None
        if clean_pw:
            if _svn_supports_password_stdin():
                # Prefer stdin so the password never lands in argv.
                args += ["--password-from-stdin"]
                stdin_input = clean_pw
            else:
                args += ["--password", clean_pw]
        if username.strip() or clean_pw:
            args += ["--non-interactive"]
        args += [repo_url.strip(), str(workdir)]
        rc, out = _run_cmd(args, cwd=root, timeout_sec=timeout_sec, stdin_input=stdin_input)
        return {"rc": rc, "output": out, "dest": str(workdir)}
    if action == "update":
        args += ["update"]
    elif action == "info":
        args += ["info"]
    else:
        return {"rc": 1, "output": "unknown action"}
    rc, out = _run_cmd(args, cwd=workdir, timeout_sec=timeout_sec)
    return {"rc": rc, "output": out, "dest": str(workdir)}


def svn_info_url(
    *,
    repo_url: str,
    username: str = "",
    password: str = "",
    timeout_sec: int = 90,
) -> Dict[str, Any]:
    if not repo_url:
        return {"rc": 1, "output": "repo_url required"}
    clean_pw, pw_error = _sanitize_password(password)
    if pw_error:
        return {"rc": 1, "output": pw_error, "revision": ""}
    args: List[str] = ["svn", "info", repo_url.strip()]
    if username.strip():
        args += ["--username", username.strip()]
    stdin_input: Optional[str] = None
    if clean_pw:
        if _svn_supports_password_stdin():
            args += ["--password-from-stdin"]
            stdin_input = clean_pw
        else:
            args += ["--password", clean_pw]
    if username.strip() or clean_pw:
        args += ["--non-interactive"]
    rc, out = _run_cmd(args, cwd=Path("."), timeout_sec=timeout_sec, stdin_input=stdin_input)
    revision = ""
    url = ""
    repo_root = ""
    if rc == 0:
        for line in out.splitlines():
            low = line.lower()
            if not revision and low.startswith("revision:"):
                revision = line.split(":", 1)[1].strip()
            elif not url and low.startswith("url:"):  # 'Relative URL:'은 매칭 안 됨
                url = line.split(":", 1)[1].strip()
            elif not repo_root and low.startswith("repository root:"):
                repo_root = line.split(":", 1)[1].strip()
    return {"rc": rc, "output": out, "revision": revision, "url": url, "repo_root": repo_root}

def svn_diff_summarize(
    *,
    repo_url: str,
    rev_a: str,
    rev_b: str,
    username: str = "",
    password: str = "",
    timeout_sec: int = 60,
) -> Dict[str, Any]:
    """`svn diff --summarize -r A:B <repo_url>` → 변경 .c/.h 파일 + editType.

    영향도 분석을 '현재 로컬 default 버전(A) ↔ 새 빌드 버전(B)' 사이의 정밀 델타에
    묶기 위한 헬퍼. URL 대상이라 워킹카피가 필요 없고(서버 조회) 빌드가 몇 번 끼어
    있든 A→B 전체 변경을 정확히 잡는다(단일 빌드 changeSet의 '빈 changeSet=0건'
    오등치 회피).

    revision은 정수 SVN revision만 허용한다(git SHA1/임의 문자열 주입 차단). status
    코드(A/M/D/R)를 editType(add/delete/edit)로 매핑하되, .c/.h 소스만 반환한다.

    Returns: {"rc": int, "output": str, "files": [rel...], "edit_types": {rel: add|edit|delete}}
    """
    ra, rb = str(rev_a or "").strip(), str(rev_b or "").strip()
    if not (ra.isdigit() and rb.isdigit()):
        return {"rc": 1, "output": "rev_a/rev_b must be numeric svn revisions", "files": [], "edit_types": {}}
    base = str(repo_url or "").strip().rstrip("/")
    if not base:
        return {"rc": 1, "output": "repo_url required", "files": [], "edit_types": {}}
    clean_pw, pw_error = _sanitize_password(password)
    if pw_error:
        return {"rc": 1, "output": pw_error, "files": [], "edit_types": {}}
    args: List[str] = ["svn", "diff", "--summarize", "-r", f"{ra}:{rb}", base]
    if username.strip():
        args += ["--username", username.strip()]
    stdin_input: Optional[str] = None
    if clean_pw:
        if _svn_supports_password_stdin():
            args += ["--password-from-stdin"]
            stdin_input = clean_pw
        else:
            args += ["--password", clean_pw]
    if username.strip() or clean_pw:
        args += ["--non-interactive"]
    rc, out = _run_cmd(args, cwd=Path("."), timeout_sec=timeout_sec, stdin_input=stdin_input)
    files: List[str] = []
    edit_types: Dict[str, str] = {}
    if rc == 0:
        for line in out.splitlines():
            s = line.rstrip()
            if not s:
                continue
            status = s[:1].upper()
            # 'M' 수정 / 'A' 추가 / 'D' 삭제 / 'R' 대체. 프로퍼티 전용 변경('_'/공백 col1)은 제외.
            if status not in ("A", "M", "D", "R"):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            url = parts[-1].strip()
            rel = url[len(base):].lstrip("/") if url.startswith(base) else url
            # svn은 URL의 비-ASCII/특수문자를 %-인코딩한다(한글 폴더 등) → by_name 로컬 경로와
            # 매칭되도록 디코딩. base(registry URL)는 미인코딩이라 prefix strip 후 디코딩한다.
            rel = unquote(rel.replace("\\", "/"))
            if not rel.lower().endswith((".c", ".h")):
                continue
            et = {"A": "add", "D": "delete"}.get(status, "edit")  # M/R → edit
            # 동일 파일 중복 라인: 구조적 변경(add/delete)을 단순 edit이 덮지 않게 보존.
            if edit_types.get(rel) not in ("add", "delete"):
                edit_types[rel] = et
            files.append(rel)
    return {
        "rc": rc,
        "output": out,
        "files": sorted(dict.fromkeys(files)),
        "edit_types": edit_types,
    }


def list_directory(project_root: str, rel_path: str = ".") -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    target = safe_resolve_under(root, rel_path or ".")
    if not target.exists() or not target.is_dir():
        return {"ok": False, "error": "not_a_directory"}
    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        try:
            entries.append(
                {
                    "name": item.name,
                    "path": str(item.relative_to(root)),
                    "is_dir": item.is_dir(),
                }
            )
        except Exception:
            continue
    return {"ok": True, "path": str(target.relative_to(root)), "entries": entries}


def git_status(project_root: str, workdir_rel: str = ".") -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    workdir = safe_resolve_under(root, workdir_rel or ".")
    rc, out = _run_cmd(["git", "status", "--porcelain=v1", "-b"], cwd=workdir)
    return {"rc": rc, "output": out}


def git_diff(project_root: str, workdir_rel: str = ".", staged: bool = False, path: str = "") -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    workdir = safe_resolve_under(root, workdir_rel or ".")
    args = ["git", "diff"]
    if staged:
        args.append("--staged")
    if path:
        args += ["--", path]
    rc, out = _run_cmd(args, cwd=workdir)
    return {"rc": rc, "output": out}


def git_log(project_root: str, workdir_rel: str = ".", max_count: int = 30) -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    workdir = safe_resolve_under(root, workdir_rel or ".")
    rc, out = _run_cmd(["git", "log", "--oneline", f"-n{int(max_count)}"], cwd=workdir)
    return {"rc": rc, "output": out}


def git_branches(project_root: str, workdir_rel: str = ".") -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    workdir = safe_resolve_under(root, workdir_rel or ".")
    rc, out = _run_cmd(["git", "branch", "--list"], cwd=workdir)
    return {"rc": rc, "output": out}


def git_checkout(project_root: str, workdir_rel: str, branch: str) -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    workdir = safe_resolve_under(root, workdir_rel or ".")
    if not branch.strip():
        return {"rc": 1, "output": "branch required"}
    rc, out = _run_cmd(["git", "checkout", branch.strip()], cwd=workdir)
    return {"rc": rc, "output": out}


def git_create_branch(project_root: str, workdir_rel: str, branch: str) -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    workdir = safe_resolve_under(root, workdir_rel or ".")
    if not branch.strip():
        return {"rc": 1, "output": "branch required"}
    rc, out = _run_cmd(["git", "checkout", "-b", branch.strip()], cwd=workdir)
    return {"rc": rc, "output": out}


def git_stage(project_root: str, workdir_rel: str, paths: List[str]) -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    workdir = safe_resolve_under(root, workdir_rel or ".")
    args = ["git", "add"]
    if paths:
        args += paths
    else:
        args.append("-A")
    rc, out = _run_cmd(args, cwd=workdir)
    return {"rc": rc, "output": out}


def git_unstage(project_root: str, workdir_rel: str, paths: List[str]) -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    workdir = safe_resolve_under(root, workdir_rel or ".")
    args = ["git", "restore", "--staged"]
    if paths:
        args += paths
    else:
        args.append(".")
    rc, out = _run_cmd(args, cwd=workdir)
    return {"rc": rc, "output": out}


def git_commit(project_root: str, workdir_rel: str, message: str) -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    workdir = safe_resolve_under(root, workdir_rel or ".")
    if not message.strip():
        return {"rc": 1, "output": "message required"}
    rc, out = _run_cmd(["git", "commit", "-m", message.strip()], cwd=workdir)
    return {"rc": rc, "output": out}


def format_c_code(text: str, filename: str = "temp.c") -> Dict[str, Any]:
    if not text:
        return {"ok": False, "error": "empty_text"}
    if not shutil.which("clang-format"):
        return {"ok": False, "error": "clang_format_missing"}
    args = ["clang-format", "-assume-filename", filename or "temp.c"]
    try:
        proc = subprocess.run(
            args,
            input=text,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        return {"ok": False, "error": f"exception: {exc}"}
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "clang-format failed").strip()
        return {"ok": False, "error": msg}
    return {"ok": True, "text": proc.stdout}


def search_in_files(project_root: str, rel_path: str, query: str, max_results: int = 200) -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    base = safe_resolve_under(root, rel_path or ".")
    if not query.strip():
        return {"ok": False, "error": "query required"}
    results: List[Dict[str, Any]] = []
    for path in base.rglob("*"):
        if len(results) >= max_results:
            break
        if path.is_dir():
            continue
        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines, start=1):
            if query in line:
                rel = str(path.relative_to(root))
                results.append({"path": rel, "line": idx, "text": line.strip()})
                if len(results) >= max_results:
                    break
    return {"ok": True, "results": results}


def replace_in_file(project_root: str, rel_path: str, search: str, replace: str) -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    target = safe_resolve_under(root, rel_path)
    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {"ok": False, "error": "read_failed"}
    if not search:
        return {"ok": False, "error": "search_required"}
    new_text = text.replace(search, replace)
    target.write_text(new_text, encoding="utf-8", errors="ignore")
    return {"ok": True, "changed": text != new_text}


def kb_dir(project_root: str, report_dir: str) -> Path:
    root = Path(project_root).resolve()
    kb_dir_name = getattr(config, "KB_DIR_NAME", "kb_store")
    return root / report_dir / kb_dir_name


def list_kb_entries(project_root: str, report_dir: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    base = kb_dir(project_root, report_dir)
    if not base.exists():
        return entries
    
    # SQLite에서 읽기 시도
    db_path = base / "kb_index.sqlite"
    if db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT id, error_raw, error_clean, fix, tags, role, stage, category, 
                       context, weight, apply_count, timestamp, source_file
                FROM kb_entries
                ORDER BY timestamp DESC
                LIMIT 1000
            """)
            for row in cur.fetchall():
                d = dict(row)
                # tags가 문자열이면 JSON 파싱
                if isinstance(d.get("tags"), str):
                    try:
                        d["tags"] = json.loads(d["tags"])
                    except Exception:
                        d["tags"] = []
                d["_source"] = "sqlite"
                entries.append(d)
            conn.close()
        except Exception:
            pass
    
    # JSON 파일에서도 읽기 (기존 방식)
    for fp in sorted(base.glob("*.json"), key=lambda p: p.name):
        if fp.name.endswith(".tmp") or fp.name.endswith(".bak") or fp.name == "kb_external_index.json":
            continue
        try:
            txt = fp.read_text(encoding="utf-8")
            if not txt.strip():
                continue
            obj = json.loads(txt)
        except Exception:
            continue
        if isinstance(obj, list):
            for i, ent in enumerate(obj):
                if not isinstance(ent, dict):
                    continue
                d = dict(ent)
                d["_file"] = fp.name
                d["_path"] = str(fp)
                d["_entry_index"] = int(i)
                d["_file_is_list"] = True
                d["_entry_key"] = f"{fp.name}#{i}"
                d["_source"] = "json"
                if "id" not in d or not str(d.get("id") or "").strip():
                    d["id"] = f"{fp.stem}:{i}"
                entries.append(d)
        elif isinstance(obj, dict):
            d = dict(obj)
            d["_file"] = fp.name
            d["_path"] = str(fp)
            d["_entry_index"] = 0
            d["_file_is_list"] = False
            d["_entry_key"] = f"{fp.name}#0"
            d["_source"] = "json"
            if "id" not in d or not str(d.get("id") or "").strip():
                d["id"] = fp.stem
            entries.append(d)
    
    # 중복 제거 (SQLite와 JSON에 동일한 항목이 있을 수 있음)
    seen_ids = set()
    unique_entries = []
    for entry in entries:
        entry_id = entry.get("id", "")
        if entry_id and entry_id not in seen_ids:
            seen_ids.add(entry_id)
            unique_entries.append(entry)
        elif not entry_id:
            unique_entries.append(entry)
    
    return unique_entries


def delete_kb_entry(entry_key: str, project_root: str, report_dir: str) -> Tuple[bool, str]:
    base = kb_dir(project_root, report_dir)
    if "#" not in (entry_key or ""):
        return False, "invalid entry key"
    fname, idx_str = entry_key.split("#", 1)
    path = (base / fname).resolve()
    if not path.exists():
        return False, "file not found"
    try:
        idx = int(idx_str)
    except Exception:
        idx = 0
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore") or "")
    except Exception:
        obj = None
    if isinstance(obj, list):
        if idx < 0 or idx >= len(obj):
            return False, "invalid index"
        new_list = [x for i, x in enumerate(obj) if i != idx]
        if not new_list:
            path.unlink(missing_ok=True)
            return True, "file deleted"
        path.write_text(json.dumps(new_list, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, "entry deleted"
    path.unlink(missing_ok=True)
    return True, "file deleted"


def read_file_text(project_root: str, rel_path: str, max_bytes: int = 2 * 1024 * 1024) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    target = safe_resolve_under(root, rel_path)
    try:
        raw = target.read_bytes()
    except Exception:
        return {"ok": False, "error": "read_failed"}
    truncated = False
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
        truncated = True
    return {"ok": True, "path": str(target), "text": raw.decode("utf-8", errors="ignore"), "truncated": truncated}


def write_file_text(project_root: str, rel_path: str, content: str, make_backup: bool = True) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    target = safe_resolve_under(root, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = ""
    if make_backup and target.exists():
        backup = str(target.with_suffix(target.suffix + ".bak"))
        try:
            Path(backup).write_bytes(target.read_bytes())
        except Exception:
            backup = ""
    target.write_text(content or "", encoding="utf-8", errors="ignore")
    return {"ok": True, "path": str(target), "backup": backup}


def replace_lines(project_root: str, rel_path: str, start_line: int, end_line: int, content: str) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    target = safe_resolve_under(root, rel_path)
    try:
        lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return {"ok": False, "error": "read_failed"}
    start = max(1, int(start_line))
    end = max(start, int(end_line))
    start_idx = start - 1
    end_idx = end
    new_lines = lines[:start_idx] + (content or "").splitlines() + lines[end_idx:]
    target.write_text("\n".join(new_lines), encoding="utf-8", errors="ignore")
    return {"ok": True, "path": str(target)}


def _pick_via_powershell(script: str) -> Tuple[str, str]:
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as exc:
        return "", f"powershell_error:{exc}"
    if res.returncode != 0:
        err = (res.stderr or res.stdout or "").strip()
        return "", f"powershell_failed:{err}"
    return (res.stdout or "").strip(), ""


def pick_directory(title: str = "폴더 선택") -> Tuple[str, str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        tk = None
        filedialog = None
    if tk and filedialog:
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(title=title or "폴더 선택")
            root.destroy()
            if not path:
                return "", "cancelled"
            return str(path), ""
        except Exception as exc:
            tk_error = f"dialog_error:{exc}"
    else:
        tk_error = "tkinter_unavailable"

    script = (
        "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
        "$dlg=New-Object System.Windows.Forms.FolderBrowserDialog;"
        f"$dlg.Description='{title or '폴더 선택'}';"
        "$dlg.ShowNewFolderButton=$true;"
        "if($dlg.ShowDialog() -eq 'OK'){ $dlg.SelectedPath }"
    )
    path, err = _pick_via_powershell(script)
    if path:
        return path, ""
    if err:
        return "", f"{tk_error}|{err}"
    return "", "cancelled"


def pick_file(title: str = "파일 선택") -> Tuple[str, str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        tk = None
        filedialog = None
    if tk and filedialog:
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(title=title or "파일 선택")
            root.destroy()
            if not path:
                return "", "cancelled"
            return str(path), ""
        except Exception as exc:
            tk_error = f"dialog_error:{exc}"
    else:
        tk_error = "tkinter_unavailable"

    script = (
        "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
        "$dlg=New-Object System.Windows.Forms.OpenFileDialog;"
        f"$dlg.Title='{title or '파일 선택'}';"
        "$dlg.Filter='All files (*.*)|*.*';"
        "if($dlg.ShowDialog() -eq 'OK'){ $dlg.FileName }"
    )
    path, err = _pick_via_powershell(script)
    if path:
        return path, ""
    if err:
        return "", f"{tk_error}|{err}"
    return "", "cancelled"
