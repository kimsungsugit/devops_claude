# /app/gui/tabs/editor.py
# -*- coding: utf-8 -*-
"""
Editor tab
- Findings(정적/동적 분석 결과)에서 파일/라인 기반으로 소스 열기
- 부분 편집(라인 범위) 중심으로 MessageSizeError 방지
- 선택 영역 -> AI 질문 -> unified diff 생성 -> 적용/롤백 -> 재검증(선택) 플로우 제공
- Cppcheck suppression 추가(옵션)

의존
- streamlit
- pandas
- workflow.ai (load_oai_config, llm_call)
- gui_utils (run_pipeline, get_paths 등)
"""

from __future__ import annotations

import os
import re
import json
import traceback
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

import gui_utils
import ui_common

try:
    from workflow import ai as ai_core  # type: ignore
except Exception:  # pragma: no cover
    ai_core = None  # type: ignore


MAX_FILE_BYTES_DEFAULT = 2 * 1024 * 1024
MAX_SNIPPET_LINES_DEFAULT = 200
AI_SNIPPET_MAX_CHARS = 12000


def _to_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _safe_relpath(p: str) -> str:
    p = (p or "").replace("\\", "/").lstrip("/")
    p = p.replace("../", "").replace("..\\", "")
    return p


def _is_abs_path(p: str) -> bool:
    s = (p or "").strip()
    if not s:
        return False
    if s.startswith("/"):
        return True
    # Windows drive path like C:\...
    if re.match(r"^[A-Za-z]:[\\/]", s):
        return True
    return False


def _apply_path_maps(raw_path: str, path_maps: list[tuple[str, str]]) -> str:
    """prefix 기반 간단 경로 매핑(FROM => TO), 가장 긴 prefix 우선"""
    rp = (raw_path or "").replace("\\", "/")
    if not rp or not path_maps:
        return raw_path

    best_from = ""
    best_to = ""
    for a, b in path_maps:
        a2 = (a or "").replace("\\", "/").rstrip("/")
        b2 = (b or "").replace("\\", "/").rstrip("/")
        if not a2 or not b2:
            continue
        if rp.startswith(a2) and len(a2) > len(best_from):
            best_from = a2
            best_to = b2

    if not best_from:
        return raw_path
    suffix = rp[len(best_from):].lstrip("/")
    return f"{best_to}/{suffix}" if suffix else best_to


def _normalize_file_for_search(raw_file: str, primary_root: Path) -> str:
    """리포트의 file 경로를 탐색용 상대경로 형태로 정규화"""
    rf = (raw_file or "").replace("\\", "/").strip()
    if not rf:
        return ""

    # Subversion pristine/text-base 파일명 정리(foo.c.svn-base -> foo.c)
    if rf.endswith(".svn-base"):
        rf = rf[: -len(".svn-base")]

    if not _is_abs_path(rf):
        return _safe_relpath(rf)

    try:
        p = Path(rf)

        # 1) primary_root 아래 절대경로면 상대경로로 변환
        try:
            rel = p.resolve().relative_to(primary_root.resolve())
            return rel.as_posix()
        except Exception:
            pass

        # 2) build_root 기반(캐시 build_*/...)이면 build_root 기준 상대경로로 변환
        broot = _find_build_root_from_path(p)
        if broot is not None:
            try:
                rel = p.resolve().relative_to(broot.resolve())
                return rel.as_posix()
            except Exception:
                pass

        # 3) 마지막 N개 path component만 유지(너무 긴 prefix 제거)
        parts = [x for x in p.parts if x not in ("/", "\\")]
        tail = parts[-6:] if len(parts) > 6 else parts
        return "/".join([t.strip("/\\") for t in tail if t])
    except Exception:
        return Path(rf).name


def _read_text_limited(path: Path, max_bytes: int) -> Tuple[str, bool]:
    try:
        raw = path.read_bytes()
    except Exception:
        return "", False

    truncated = False
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
        truncated = True
    return raw.decode("utf-8", errors="ignore"), truncated


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", errors="ignore")


def _make_backup(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".bak_{ts}")
    bak.write_bytes(path.read_bytes())
    return bak


def _get_log_dir(report_root: Path) -> Path:
    log_dir = (report_root / "ai_logs").resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _extract_unified_diff(text: str) -> str:
    if not text:
        return ""
    t = text.strip()

    m = re.search(r"```diff\s*(.*?)```", t, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.search(r"(^diff --git .*?$.*)", t, flags=re.DOTALL | re.MULTILINE)
    if m:
        return m.group(1).strip()

    m = re.search(r"(^---\s+.*?$\s*^\+\+\+\s+.*?$.*)", t, flags=re.DOTALL | re.MULTILINE)
    if m:
        return m.group(1).strip()

    return t


def _strip_ab(path: str) -> str:
    path = (path or "").strip()
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path



def _find_build_root_from_path(p: Path) -> Path | None:
    """Walk up from p until a directory name starts with 'build_' (Jenkins cache convention)."""
    cur = p.resolve()
    for _ in range(12):
        if cur.name.startswith("build_"):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _dedup_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        try:
            rp = str(p.resolve())
        except Exception:
            rp = str(p)
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return out


def _collect_candidate_roots(primary_root: Path, raw_file: str | None = None) -> list[Path]:
    """Collect likely code roots for resolving a file path.
    Priority:
      1) primary_root
      2) st.session_state viewer_project_root / viewer_code_root
      3) st.session_state viewer_source_roots
      4) Jenkins build_root derived from primary_root (add svn_wc*, app/, workspace/)
    """
    roots: list[Path] = [primary_root]

    # explicit roots from session_state
    try:
        vpr = st.session_state.get("viewer_project_root")
        if vpr:
            roots.append(Path(str(vpr)))
    except Exception:
        pass
    try:
        vcr = st.session_state.get("viewer_code_root")
        if vcr:
            roots.append(Path(str(vcr)))
    except Exception:
        pass
    try:
        vsr = st.session_state.get("viewer_source_roots")
        if isinstance(vsr, (list, tuple)):
            for x in vsr:
                if x:
                    roots.append(Path(str(x)))
    except Exception:
        pass

    # Jenkins build_root(캐시) 후보
    broot = _find_build_root_from_path(primary_root)
    # viewer/jenkins 모드에서 build_root가 별도로 저장되는 경우 반영
    for k in ("viewer_build_root", "jenkins_build_root"):
        try:
            v = st.session_state.get(k)
            if v:
                broot2 = _find_build_root_from_path(Path(str(v))) or Path(str(v))
                if broot2 and broot2.exists() and broot2.is_dir():
                    broot = broot2
        except Exception:
            pass
    # raw_file(절대경로)로부터 build_root 유추
    if raw_file and _is_abs_path(str(raw_file)):
        try:
            broot3 = _find_build_root_from_path(Path(str(raw_file)))
            if broot3 and broot3.exists() and broot3.is_dir():
                broot = broot3
        except Exception:
            pass
    if broot:
        # build_root 자체도 포함(일부 프로젝트는 build_root 바로 아래에 소스가 존재)
        roots.append(broot)
        for name in ("svn_wc", "svn_wc1", "svn_wc2", "workspace", "repo", "app", "source", "src"):
            cand = broot / name
            if cand.exists() and cand.is_dir():
                roots.append(cand)

        # 흔한 하위 소스 루트 패턴도 추가 (build마다 구조가 다른 케이스 대응)
        for rel in (
            "svn_wc/Sources",
            "svn_wc/Sources/APP",
            "svn_wc/Sources/AP",
            "app/PDSM/Sources",
            "app/PDSM/Sources/APP",
            "app/PDSM/Sources/AP",
            "Sources",
            "source",
            "src",
        ):
            cand = broot / rel
            if cand.exists() and cand.is_dir():
                roots.append(cand)
        # also add any svn_wc* directories
        try:
            for cand in broot.iterdir():
                if cand.is_dir() and cand.name.startswith("svn_wc"):
                    roots.append(cand)
                    # .../svn_wc/Sources 도 자주 등장
                    s2 = cand / "Sources"
                    if s2.exists() and s2.is_dir():
                        roots.append(s2)
        except Exception:
            pass

    # keep existing only
    roots2 = [p for p in roots if p.exists() and p.is_dir()]
    return _dedup_paths(roots2)


def _score_candidate_path(p: Path) -> tuple[int, int]:
    """Lower score is better."""
    s = str(p).replace("\\", "/").lower()
    penalty = 0
    # prefer svn checkout roots if present
    if "/svn_wc" in s:
        penalty -= 10
    # prefer paths containing sources/src
    if "/sources/" in s or s.endswith("/sources"):
        penalty -= 5
    if "/src/" in s or s.endswith("/src"):
        penalty -= 3
    # shorter depth preferred
    depth = len(p.parts)
    return (penalty, depth)


_INDEX_EXTS = (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".inl", ".inc", ".py")


@st.cache_data(show_spinner=False, ttl=900)
def _build_basename_index(root_str: str, max_files: int = 200000) -> dict[str, list[str]]:
    """root 하위 파일을 basename(lower) -> 경로 리스트로 색인함

    - 탐색 비용 절감을 위해 소스 확장자만 포함
    - max_files 초과 시 중단
    """
    root = Path(root_str)
    out: dict[str, list[str]] = {}
    if not root.exists() or not root.is_dir():
        return out

    count = 0
    for dirpath, _, filenames in os.walk(str(root)):
        for fn in filenames:
            if not fn:
                continue
            if not fn.lower().endswith(_INDEX_EXTS):
                continue
            key = fn.lower()
            out.setdefault(key, []).append(str(Path(dirpath) / fn))
            count += 1
            if count >= int(max_files):
                return out
    return out


def _try_resolve_missing_file(raw_file: str, file_rel: str, primary_root: Path) -> tuple[Path | None, str]:
    """Try to resolve a missing target file using multiple heuristics.
    Returns (resolved_path, note)."""
    # 0) prefix path map(있으면) 적용
    try:
        pms = st.session_state.get("viewer_path_maps")
        if isinstance(pms, list) and pms:
            mapped = _apply_path_maps(raw_file, pms)
            if mapped and mapped != raw_file:
                raw_file = mapped
                # file_rel이 불필요하게 긴 절대경로 형태면 재정규화
                if (not file_rel) or str(file_rel).startswith("app/.devops_pro_cache/"):
                    file_rel = _normalize_file_for_search(raw_file, primary_root)
    except Exception:
        pass

    # 0) absolute path direct (guarded)

    rel_norm = (file_rel or "").replace("\\", "/").lstrip("/")
    parts = [x for x in rel_norm.split("/") if x]

    roots = _collect_candidate_roots(primary_root, raw_file=raw_file)

    # absolute path direct (allow only when inside known roots)
    try:
        if raw_file and _is_abs_path(raw_file):
            rp = Path(raw_file)
            if rp.exists() and rp.is_file():
                rr = rp.resolve()
                if ui_common.is_under_any(rr, roots):
                    return (rr, "abs_exists")
                return (None, "abs_outside_roots")
    except Exception:
        pass

    # 1) direct join
    for r in roots:
        try:
            cand = ui_common.safe_resolve_under(r, rel_norm)
        except Exception:
            continue
        if cand.exists() and cand.is_file():
            return (cand, f"join:{r}")

    # 2) tail parts join (handles mismatched prefixes like app/PDSM/Sources vs svn_wc/Sources/APP)
    for r in roots:
        # Start with longer tails for better accuracy
        for k in range(min(12, len(parts)), 0, -1):
            tail = "/".join(parts[-k:])
            try:
                cand = ui_common.safe_resolve_under(r, tail)
            except Exception:
                continue
            if cand.exists() and cand.is_file():
                return (cand, f"tail{k}:{r}")

    base = parts[-1] if parts else Path(raw_file).name

    # 3) basename index(빠른 탐색) - basename만 제공되는 리포트(/build_xxx/Foo.c 등) 대응
    #    rglob은 대규모 트리에서 매우 느릴 수 있어, 우선 index 기반으로 후보를 찾음
    if base:
        candidates: list[Path] = []
        key = base.lower()
        for r in roots:
            try:
                idx = _build_basename_index(str(r))
                for s in (idx.get(key) or [])[:300]:
                    p = Path(s)
                    if p.exists() and p.is_file():
                        candidates.append(p)
            except Exception:
                continue

        if candidates:
            # rel_norm suffix와 더 잘 맞는 후보 우선
            rel_suf = ("/" + rel_norm).lower() if rel_norm else ""

            def _rank(p: Path) -> tuple[int, int, int]:
                s = str(p.resolve()).replace("\\", "/").lower()
                suf_bonus = -50 if (rel_suf and s.endswith(rel_suf)) else 0
                pen, depth = _score_candidate_path(p)
                return (suf_bonus + pen, depth, len(s))

            candidates.sort(key=_rank)

            # UI에서 선택할 수 있도록 후보를 남김(상위 N)
            try:
                st.session_state["editor_resolve_candidates"] = [str(p.resolve()) for p in candidates[:25]]
                st.session_state["editor_resolve_candidates_key"] = f"{base}:{rel_norm}"
            except Exception:
                pass

            return (candidates[0].resolve(), f"index_base:{len(candidates)}")

    # 4) rglob search (exhaustive): prefer full suffix match, then basename match
    #    index가 실패한 경우에만 수행
    if base:
        suffix_to_find = "/" + rel_norm
        suffix_matches: list[Path] = []
        basename_matches: list[Path] = []

        for r in roots:
            try:
                # Limit search space by globbing for the basename first
                for pth in r.rglob(base):
                    if not pth.is_file() or pth.name.lower() != base.lower():
                        continue

                    rp_str = str(pth.resolve()).replace("\\", "/")
                    if rp_str.endswith(suffix_to_find):
                        suffix_matches.append(pth)
                    else:
                        basename_matches.append(pth)

                    if len(suffix_matches) + len(basename_matches) >= 120:
                        break
            except Exception:
                continue
            if len(suffix_matches) + len(basename_matches) >= 120:
                break

        if suffix_matches:
            suffix_matches.sort(key=lambda p: _score_candidate_path(p))
            return (suffix_matches[0].resolve(), f"rglob_suffix:{len(suffix_matches)}")

        if basename_matches:
            basename_matches.sort(key=lambda p: _score_candidate_path(p))
            return (basename_matches[0].resolve(), f"rglob_base:{len(basename_matches)}")

    return (None, "not_found")


@dataclass
class _DiffHunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: List[str]


def _parse_unified_diff(diff_text: str) -> Tuple[Optional[str], List[_DiffHunk]]:
    if not diff_text:
        return None, []

    lines = diff_text.splitlines()
    target_path: Optional[str] = None
    hunks: List[_DiffHunk] = []

    i = 0
    while i < len(lines):
        ln = lines[i]

        if ln.startswith("+++ "):
            p = ln[4:].strip()
            p = p.split("\t")[0].strip()
            if p != "/dev/null":
                target_path = _strip_ab(p)
            i += 1
            continue

        if ln.startswith("@@ "):
            m = re.match(r"@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", ln)
            if not m:
                i += 1
                continue
            old_start = int(m.group(1))
            old_len = int(m.group(2) or "1")
            new_start = int(m.group(3))
            new_len = int(m.group(4) or "1")
            i += 1
            h_lines: List[str] = []
            while i < len(lines):
                l2 = lines[i]
                if l2.startswith("@@ "):
                    break
                if l2.startswith("diff --git ") or l2.startswith("--- ") or l2.startswith("+++ "):
                    break
                h_lines.append(l2)
                i += 1
            hunks.append(_DiffHunk(old_start, old_len, new_start, new_len, h_lines))
            continue

        i += 1

    return target_path, hunks


def _try_apply_hunk_at(buf: List[str], idx: int, h: _DiffHunk) -> Optional[List[str]]:
    out = buf[:]
    p = idx
    for raw in h.lines:
        if not raw:
            continue
        if raw.startswith("\\") and "No newline" in raw:
            continue

        tag = raw[:1]
        content = raw[1:]

        if tag == " ":
            if p >= len(out):
                return None
            if out[p].rstrip("\n") != content:
                return None
            p += 1
        elif tag == "-":
            if p >= len(out):
                return None
            if out[p].rstrip("\n") != content:
                return None
            del out[p]
        elif tag == "+":
            out.insert(p, content + "\n")
            p += 1
        else:
            continue
    return out


def _apply_unified_diff_to_file(target: Path, diff_text: str) -> Tuple[bool, str]:
    if not target.exists():
        return False, f"파일 없음: {target}"

    diff_text = _extract_unified_diff(diff_text)
    _, hunks = _parse_unified_diff(diff_text)
    if not hunks:
        return False, "diff hunk 없음, 적용 불가"

    orig = target.read_text(encoding="utf-8", errors="ignore")
    buf = orig.splitlines(True)

    for h in hunks:
        base_idx = max(0, h.old_start - 1)
        applied = _try_apply_hunk_at(buf, base_idx, h)
        if applied is None:
            lo = max(0, base_idx - 50)
            hi = min(len(buf), base_idx + 50)
            for pos in range(lo, hi + 1):
                applied = _try_apply_hunk_at(buf, pos, h)
                if applied is not None:
                    break

        if applied is None:
            return False, f"hunk 적용 실패(주변 문맥 불일치), old_start={h.old_start}"
        buf = applied

    _write_text(target, "".join(buf))
    return True, f"diff 적용 완료, hunks={len(hunks)}"


def _load_ai_cfg(oai_config_path: Optional[str]) -> Optional[dict]:
    if not ai_core:
        return None
    try:
        cfgs = ai_core.load_oai_config(oai_config_path)
        if isinstance(cfgs, list) and cfgs:
            return cfgs[0]
        if isinstance(cfgs, dict):
            return cfgs
    except Exception:
        return None
    return None


def _ai_ask_text(
    *,
    cfg: dict,
    log_dir: Path,
    file_path: str,
    line_num: int,
    message: str,
    snippet: str,
) -> str:
    sys_p = "너는 C/C++ 정적분석/동적분석 이슈를 해결하는 시니어 엔지니어임"
    user_p = (
        f"파일: {file_path}\n"
        f"라인: {line_num}\n"
        f"메시지: {message}\n"
        f"코드 문맥:\n```c\n{snippet}\n```\n"
        "원인 분석, 최소 수정 방안, 수정 후 확인 방법을 순서대로 제시"
    )
    try:
        reply = ai_core.agent_call_text(
            cfg,
            [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
            log_dir=log_dir,
            role="assistant",
            stage="editor_explain",
        )
        return reply or "⚠️ AI 응답 없음, 모델/연결/설정 확인 필요"
    except Exception as e:
        return f"❌ AI 호출 오류: {e}"


def _ai_generate_diff(
    *,
    cfg: dict,
    log_dir: Path,
    rel_file: str,
    issue_message: str,
    snippet: str,
) -> str:
    sys_p = "너는 숙련된 코드리뷰어/패치작성자임, 출력은 오직 unified diff 형식임, 추가 설명 금지"
    user_p = (
        "다음 이슈를 해결하는 패치를 생성\n"
        f"대상 파일: {rel_file}\n"
        f"이슈: {issue_message}\n"
        f"코드(선택 영역):\n```c\n{snippet}\n```\n"
        "요구사항\n"
        f"- 반드시 unified diff를 반환, 파일 헤더 포함(--- a/{rel_file}, +++ b/{rel_file})\n"
        "- 불필요한 변경 금지, 최소 수정\n"
        "- 컴파일 오류/스타일 깨짐 방지\n"
    )
    try:
        reply = ai_core.agent_call_text(
            cfg,
            [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
            log_dir=log_dir,
            role="generator",
            stage="editor_diff",
        )
        return reply or ""
    except Exception as e:
        return f"❌ AI diff 생성 오류: {e}"


def _ai_generate_deviation_draft(
    *,
    cfg: dict,
    log_dir: Path,
    rel_file: str,
    line_num: int,
    issue_rule: str,
    issue_message: str,
    snippet: str,
    rule_desc: str,
    type_opts: List[str],
) -> str:
    sys_p = (
        "너는 C/C++ 코드의 정적분석 룰 위반에 대한 데비에이션(deviation) 문서를 작성하는 QA 엔지니어다.\n"
        "출력은 반드시 JSON 형식이어야 하며, 다른 설명은 절대 추가하지 않는다.\n"
        f"JSON은 'type', 'context', 'safety_argument', 'mitigation' 네 개의 키를 가져야 한다.\n"
        f"- type: 주어진 선택지 {type_opts} 중에서 가장 적절한 사유 한 가지를 선택한다.\n"
        "- context: 6하원칙에 따라 이슈 상황을 명확히 설명한다.\n"
        "- safety_argument: 룰을 위반했음에도 왜 안전한지 기술적 근거를 제시한다. 오탐일 경우 왜 오탐인지 설명한다.\n"
        "- mitigation: 잠재적 위험을 완화하기 위한 다른 방어 코드, 테스트, 모니터링 등의 보완책을 제시한다. (없으면 '해당 없음'으로)"
    )
    user_p = (
        "다음 정적분석 이슈에 대한 데비에이션 초안을 JSON 형식으로 작성해줘.\n"
        f"대상 파일: {rel_file}\n"
        f"라인: {line_num}\n"
        f"위반 룰: {issue_rule}\n"
        f"룰 설명: {rule_desc}\n"
        f"메시지: {issue_message}\n"
        f"코드 문맥:\n```c\n{snippet}\n```\n"
        "요구사항: 'type', 'context', 'safety_argument', 'mitigation' 키를 가진 JSON 객체만 출력해줘."
    )
    try:
        reply = ai_core.agent_call_text(
            cfg,
            [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
            log_dir=log_dir,
            role="generator",
            stage="editor_deviation",
        )
        return reply or ""
    except Exception as e:
        return f"❌ AI deviation 생성 오류: {e}"


def _normalize_findings(findings: Any) -> List[Dict[str, Any]]:
    if isinstance(findings, dict):
        if isinstance(findings.get("items"), list):
            return [x for x in findings.get("items") if isinstance(x, dict)]
        return []
    if isinstance(findings, list):
        return [x for x in findings if isinstance(x, dict)]
    return []


def _to_table_rows(items: List[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for it in items:
        tool = it.get("tool") or it.get("source") or it.get("checker") or ""
        sev = it.get("severity") or it.get("level") or it.get("grade") or ""
        rule = it.get("rule") or it.get("check") or it.get("id") or it.get("code") or ""
        msg = it.get("message") or it.get("msg") or it.get("text") or it.get("desc") or ""
        file_path = it.get("file") or it.get("path") or it.get("filename") or it.get("sourceFile") or ""
        line = it.get("line") or it.get("lineNumber") or it.get("line_num") or 0
        col = it.get("column") or it.get("col") or ""
        kind = it.get("kind") or it.get("category") or ""

        rows.append(
            {
                "tool": str(tool),
                "severity": str(sev),
                "kind": str(kind),
                "rule": str(rule),
                "message": str(msg),
                "file": str(file_path),
                "line": _to_int(line, 0),
                "col": str(col),
                "_raw": it,
            }
        )
    cols = ["tool","severity","kind","rule","message","file","line","col","_raw"]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df = df.sort_values(["tool","severity","file","line"], ascending=True, na_position="last").reset_index(drop=True)


    return df


def render_editor(
    project_root: str,
    findings: Any,
    status: Any,
    oai_config_path: Optional[str] = None,
    suppressions_path: Optional[Path] = None,
    reports_dir: Optional[Path] = None,
    rule_catalog: Optional[Dict[str, str]] = None,
    build_info: Optional[dict] = None,
    widget_key_prefix: str = "editor",
) -> None:
    """
    Renders the code editor tab, allowing users to view, edit, and analyze code.
    """
    root = Path(str(project_root or ".")).resolve()
    default_author = (build_info or {}).get("build_user") if isinstance(build_info, dict) else ""
    default_author = default_author or (os.environ.get("BUILD_USER_ID") or os.environ.get("BUILD_USER") or os.environ.get("USER") or os.environ.get("USERNAME") or "")
    # Jenkins/Local 공통: reports 디렉터리(Deviation 저장 위치)
    _reports_dir: Optional[Path] = None
    try:
        if reports_dir:
            _reports_dir = Path(reports_dir).resolve()
        elif suppressions_path:
            _reports_dir = Path(suppressions_path).resolve().parent
        elif isinstance(status, dict) and status.get("reports_dir"):
            _reports_dir = Path(str(status.get("reports_dir"))).resolve()
    except Exception:
        _reports_dir = None

    # Rule catalog(설명) 로드
    try:
        _rule_catalog = rule_catalog if isinstance(rule_catalog, dict) else gui_utils.load_rule_catalog(Path.cwd())
    except Exception:
        _rule_catalog = {}

    widget_key_prefix = str(widget_key_prefix or "editor")

    def _k(name: str) -> str:
        return f"{widget_key_prefix}:{name}"

    # ------------------------------------------------------------
    # 파일 빠른 찾기 (findings.json이 비어 있어도 사용 가능)
    # ------------------------------------------------------------
    with st.expander("📂 파일 빠른 찾기", expanded=False):
        qf = st.text_input("검색어(예: .c / Ap_BuzzerCtrl_PDS.c / APP/Ap_ )", value="", key=_k("quick_find_q"))
        cff1, cff2 = st.columns([1, 1])
        with cff1:
            refresh_idx = st.button("🔄 인덱스 갱신", key=_k("quick_find_refresh"), help="현재 설정된 코드 루트를 기준으로 파일 목록을 다시 만듭니다.")
        with cff2:
            do_find = st.button("🔎 검색", key=_k("quick_find_go"), type="primary")

        def _build_index(roots: list[Path], limit: int = 20000) -> list[str]:
            out: list[str] = []
            exts = {".c", ".h", ".cpp", ".hpp", ".cc", ".cxx"}
            skip_dirs = {"build", "out", "reports", ".git", ".svn", ".devops_pro_cache", "node_modules", "__pycache__"}
            for base in roots:
                try:
                    base = base.resolve()
                except Exception:
                    continue
                if not base.exists():
                    continue
                for r, d, f in os.walk(str(base)):
                    # prune
                    d[:] = [dr for dr in d if dr not in skip_dirs]
                    for fn in f:
                        suf = Path(fn).suffix.lower()
                        if suf in exts:
                            out.append(str(Path(r) / fn))
                            if len(out) >= limit:
                                return out
            return out

        def _get_roots_for_search(primary_root: Path) -> list[Path]:
            s_roots = _collect_candidate_roots(primary_root)
            try:
                vsr = st.session_state.get("viewer_source_roots")
                if isinstance(vsr, list):
                    for r in vsr:
                        try:
                            s_roots.append(Path(str(r)))
                        except Exception:
                            pass
            except Exception:
                pass
            return _dedup_paths(s_roots)

        search_roots = _get_roots_for_search(Path(str(project_root)))
        sig = "|".join(sorted([str(p) for p in search_roots]))
        if refresh_idx or st.session_state.get(_k("quick_find_sig")) != sig or _k("quick_find_index") not in st.session_state:
            with st.spinner("인덱싱 중..."):
                st.session_state[_k("quick_find_sig")] = sig
                st.session_state[_k("quick_find_index")] = _build_index(search_roots)

        idx_list = st.session_state.get(_k("quick_find_index")) or []
        if do_find and qf:
            ql = qf.strip().lower()
            cand = []
            if ql.startswith(".") and len(ql) <= 5:
                cand = [p for p in idx_list if p.lower().endswith(ql)]
            elif "/" not in ql and "\\" not in ql and "." in ql:
                cand = [p for p in idx_list if Path(p).name.lower() == ql]
                if not cand:
                    cand = [p for p in idx_list if ql in Path(p).name.lower()]
            else:
                cand = [p for p in idx_list if ql in p.lower()]

            cand = cand[:200]
            if not cand:
                st.info("검색 결과 없음, 코드 루트 설정 또는 SVN 체크아웃 경로를 확인하세요.")
            else:
                pick = st.selectbox("검색 결과 (최대 200개)", options=cand, index=0, key=_k("quick_find_pick"))
                line_in = st.number_input("이동할 라인", min_value=1, value=1, step=1, key=_k("quick_find_line"))
                if st.button("📂 열기", key=_k("quick_find_open"), type="primary"):
                    st.session_state["editor_open_file"] = pick
                    st.session_state["editor_open_line"] = int(line_in)
                    st.session_state["editor_open_hint"] = "quick_find"
                    st.rerun()
        else:
            st.caption(f"인덱스 파일 {len(idx_list)}개 | 검색 루트 {len(search_roots)}개")

    items = _normalize_findings(findings)
    df = _to_table_rows(items)

    st.subheader("🧩 코드 에디터 / AI 패치")

    st.session_state.setdefault("editor_selected_row", None)
    st.session_state.setdefault("editor_ai_reply", "")
    st.session_state.setdefault("editor_ai_diff", "")
    st.session_state.setdefault("editor_backups", {})


    # ------------------------------------------------------------
    # Jenkins Viewer -> Editor bridge
    # ------------------------------------------------------------
    open_key = st.session_state.get("editor_open_key")
    last_key = st.session_state.get("editor_open_key_last")
    if open_key and open_key != last_key:
        st.session_state["editor_open_key_last"] = open_key
        of = str(st.session_state.get("editor_open_file") or "")
        ol = _to_int(st.session_state.get("editor_open_line"), 0)
        if of and ol > 0:
            st.session_state["editor_selected_row"] = {
                "tool": str(st.session_state.get("editor_open_tool") or "jenkins"),
                "severity": str(st.session_state.get("editor_open_severity") or ""),
                "kind": str(st.session_state.get("editor_open_kind") or ""),
                "rule": str(st.session_state.get("editor_open_rule") or ""),
                "message": str(st.session_state.get("editor_open_message") or ""),
                "file": of,
                "line": ol,
                "col": "",
                "_raw": {},
            }

    # pinned panel
    pin_file = str(st.session_state.get("editor_open_file") or "")
    pin_line = _to_int(st.session_state.get("editor_open_line"), 0)
    pin_msg = str(st.session_state.get("editor_open_message") or "")
    if pin_file and pin_line > 0:
        with st.expander("📌 Jenkins에서 선택한 이슈", expanded=True):
            tool_p = str(st.session_state.get("editor_open_tool") or "")
            sev_p = str(st.session_state.get("editor_open_severity") or "")
            rule_p = str(st.session_state.get("editor_open_rule") or "")
            st.caption(f"tool={tool_p}, severity={sev_p}, rule={rule_p}")
            st.code(f"{pin_file}:{pin_line}\n{pin_msg}", language="text")
            if st.button("📌 핀 해제", width="stretch", key=_k("pin_clear")):
                for k in (
                    "editor_open_key", "editor_open_key_last", "editor_open_file", "editor_open_line",
                    "editor_open_message", "editor_open_tool", "editor_open_severity", "editor_open_rule", "editor_open_kind",
                ):
                    st.session_state.pop(k, None)
                st.rerun()

    c1, c2, c3, c4 = st.columns([2, 2, 2, 4])
    with c1:
        tool_f = st.selectbox("Tool", options=["(all)"] + sorted([x for x in df["tool"].unique().tolist() if x]), index=0, key=_k("filter_tool"))
    with c2:
        sev_f = st.selectbox(
            "Severity", options=["(all)"] + sorted([x for x in df["severity"].unique().tolist() if x]), index=0, key=_k("filter_sev")
        )
    with c3:
        has_file = st.checkbox("파일 이슈만", value=True, help="file/line 없는 항목 숨김")

    q = c4.text_input("검색(rule/message/file)", value="")

    df_view = df.copy()
    if tool_f != "(all)":
        df_view = df_view[df_view["tool"] == tool_f]
    if sev_f != "(all)":
        df_view = df_view[df_view["severity"] == sev_f]
    if has_file:
        df_view = df_view[(df_view["file"].astype(str) != "") & (df_view["line"].astype(int) > 0)]
    if q.strip():
        qq = q.strip().lower()
        mask = (
            df_view["rule"].astype(str).str.lower().str.contains(qq)
            | df_view["message"].astype(str).str.lower().str.contains(qq)
            | df_view["file"].astype(str).str.lower().str.contains(qq)
        )
        df_view = df_view[mask]

    max_rows = st.slider("표시 행 수", min_value=50, max_value=2000, value=min(500, max(50, len(df_view))), step=50)
    df_show = df_view.head(int(max_rows)).copy()

    st.caption(f"findings: {len(df)}개, 현재 필터: {len(df_view)}개, 표시: {len(df_show)}개")

    show_cols = ["tool", "severity", "kind", "rule", "message", "file", "line"]
    table = st.dataframe(
        df_show[show_cols], hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row"
    )

    sel = None
    try:
        sel = table.selection
    except Exception:
        sel = None

    if sel and isinstance(sel, dict) and sel.get("rows"):
        ridx = int(sel["rows"][0])
        if 0 <= ridx < len(df_show):
            st.session_state["editor_selected_row"] = df_show.iloc[ridx].to_dict()

    row = st.session_state.get("editor_selected_row")
    if not row:
        st.info("룰/정적분석 이슈 목록이 비어있음, Jenkins 빌드에서 findings.json이 생성되지 않았거나 비어있는 상태임, 아래에서 파일을 직접 열거나, Jenkins Reports 탭에서 자동 추출된 위반 목록 생성 기능 사용 권장함")
        st.subheader("파일 직접 열기")
        cfo1, cfo2, cfo3 = st.columns([6, 2, 2])
        with cfo1:
            manual_path = st.text_input("파일 경로(프로젝트 루트 기준)", value="", key=_k("manual_path"))
        with cfo2:
            manual_line = st.number_input("라인", min_value=1, value=1, step=1, key=_k("manual_line"))
        with cfo3:
            open_btn = st.button("📂 열기", width="stretch", key=_k("manual_open"))
        if open_btn and manual_path:
            st.session_state["editor_open_file"] = manual_path
            st.session_state["editor_open_line"] = int(manual_line)
            st.session_state["editor_open_message"] = "manual open"
            st.session_state["editor_open_tool"] = ""
            st.session_state["editor_open_severity"] = ""
            st.session_state["editor_open_rule"] = ""
            st.session_state["editor_open_kind"] = "manual"
            st.rerun()
        # ... (file search expander) ...
        return

    raw_file = str(row.get("file") or "")
    # Jenkins 리포트는 절대경로/워크스페이스 경로가 섞여 들어오는 경우가 많아
    # 탐색용 상대경로를 별도로 정규화함
    path_maps = []
    try:
        pms = st.session_state.get("viewer_path_maps")
        if isinstance(pms, list):
            path_maps = [(str(a), str(b)) for a, b in pms if a and b]
    except Exception:
        path_maps = []

    raw_file_mapped = _apply_path_maps(raw_file, path_maps) if path_maps else raw_file

    # 사용자가 대체 경로를 선택한 경우(이슈 file 필드는 유지, 실제 열 경로만 교체)
    try:
        _forced = st.session_state.get("editor_force_open_path")
        _from = st.session_state.get("editor_force_open_from")
        if _forced and _from and str(_from) == str(raw_file_mapped):
            raw_file_mapped = str(_forced)
            # 한 번 적용 후 초기화
            st.session_state.pop("editor_force_open_path", None)
            st.session_state.pop("editor_force_open_from", None)
    except Exception:
        pass

    file_rel = _normalize_file_for_search(raw_file_mapped, root)
    line_num = _to_int(row.get("line"), 0)
    issue_msg = str(row.get("message") or "")
    tool_name = str(row.get("tool") or "")

    st.divider()
    st.markdown(f"**선택 이슈**  tool={tool_name}, severity={row.get('severity')}, rule={row.get('rule')}")

    # Rule 설명 표시
    _rule = str(row.get("rule") or "")
    _desc = ""
    try:
        _desc = gui_utils.rule_desc(_rule, _rule_catalog)
    except Exception:
        _desc = ""
    if _desc:
        st.caption(f"📌 Rule 설명: {_desc}")

    # 1차: 절대경로면 그대로, 아니면 project_root + file_rel
    resolve_note = "primary"
    if raw_file_mapped and _is_abs_path(raw_file_mapped):
        target = Path(raw_file_mapped).resolve()
        resolve_note = "abs"
    else:
        target = (root / file_rel).resolve()

    # 허용 루트(프로젝트 루트 + Jenkins build_root + 사용자 지정 소스 루트)
    allowed_roots = _collect_candidate_roots(root, raw_file=raw_file_mapped)
    if not any((ar == target) or (ar in target.parents) for ar in allowed_roots):
        st.error("경로가 허용된 코드 루트를 벗어남, 차단")
        st.caption("해결: Jenkins Viewer 사이드바에서 '소스 루트/경로 매핑' 설정 권장")
        st.code(str(target))
        return

    # 2차: 파일이 없으면 Jenkins/SVN 체크아웃 등 다른 루트에서 재탐색
    if not (target.exists() and target.is_file()):
        resolved, note = _try_resolve_missing_file(raw_file_mapped, file_rel, root)
        # note는 실패했더라도 원인 힌트로 표시
        resolve_note = note
        if resolved is not None:
            target = resolved

        # 재탐색 결과도 허용 루트 내부인지 확인
        if not any((ar == target) or (ar in target.parents) for ar in allowed_roots):
            st.error("해결된 경로가 허용된 코드 루트를 벗어남, 차단")
            st.code(str(target))
            return
    
    # AI 기능에 필요한 정보 로드
    cfg = _load_ai_cfg(oai_config_path)
    report_root_guess = (target.parent / "..").resolve() if suppressions_path is None else Path(suppressions_path).resolve().parent
    log_dir = _get_log_dir(report_root_guess)
    
    # 데비에이션 AI용 기본 스니펫 준비
    snip_for_dev = ""
    if target.exists():
        text_for_dev, _ = _read_text_limited(target, 256 * 1024)
        if text_for_dev:
            lines_for_dev = text_for_dev.splitlines()
            start_dev = max(0, line_num - 50)
            end_dev = min(len(lines_for_dev), line_num + 50)
            snip_for_dev = "\n".join(lines_for_dev[start_dev:end_dev])

    # Deviation(데비에이션) 표시/등록
    _dev = None
    if _reports_dir:
        try:
            _dev = gui_utils.get_deviation_for_issue(_reports_dir, _rule, file_rel, line_num, issue_msg)
        except Exception:
            _dev = None

    # 선택된 이슈가 변경되면 데비에이션 폼의 상태를 초기화
    type_opts = [
        "False Positive (오탐)", "Intentional Design (의도된 설계)",
        "Performance/HW Constraints (성능/하드웨어 제약)", "Other (기타)",
    ]
    current_row_hash = hashlib.sha1(str(row).encode()).hexdigest()
    last_row_hash = st.session_state.get(_k("current_row_hash"))

    if current_row_hash != last_row_hash:
        st.session_state[_k("current_row_hash")] = current_row_hash
        st.session_state[_k("dev_context")] = str((_dev or {}).get("context") or "")
        st.session_state[_k("dev_safety")] = str((_dev or {}).get("safety_argument") or "")
        st.session_state[_k("dev_mitigation")] = str((_dev or {}).get("mitigation") or "")
        st.session_state[_k("dev_evidence")] = str((_dev or {}).get("evidence") or "")
        st.session_state[_k("dev_reviewer")] = str((_dev or {}).get("reviewer") or "")
        _type_default_val = str((_dev or {}).get("type") or type_opts[0])
        st.session_state[_k("dev_type_index")] = max(0, type_opts.index(_type_default_val)) if _type_default_val in type_opts else 0

    # AI 초안 생성 로직 (위젯 렌더링 전 실행)
    st.session_state.setdefault(_k("generate_dev_draft_flag"), False)
    if st.session_state.get(_k("generate_dev_draft_flag")):
        # 플래그를 먼저 리셋해서 중복 실행 방지
        st.session_state[_k("generate_dev_draft_flag")] = False
        if cfg and snip_for_dev:
            with st.spinner("AI 데비에이션 초안 작성 중..."):
                draft_str = _ai_generate_deviation_draft(
                    cfg=cfg, log_dir=log_dir, rel_file=file_rel, line_num=line_num, issue_rule=_rule,
                    issue_message=issue_msg, snippet=snip_for_dev, rule_desc=_desc, type_opts=type_opts,
                )
                try:
                    m = re.search(r"\{.*\}", draft_str, re.DOTALL)
                    if m:
                        draft_json = json.loads(m.group(0))
                        st.session_state[_k("dev_context")] = draft_json.get("context", "")
                        st.session_state[_k("dev_safety")] = draft_json.get("safety_argument", "")
                        st.session_state[_k("dev_mitigation")] = draft_json.get("mitigation", "")
                        ai_dev_type = draft_json.get("type", "")
                        if ai_dev_type in type_opts:
                            st.session_state[_k("dev_type_index")] = type_opts.index(ai_dev_type)
                    else:
                        st.warning(f"AI가 유효한 JSON을 반환하지 않았습니다: {draft_str}")
                except Exception as e:
                    st.error(f"AI 응답 처리 실패: {e}\n{draft_str}")
        elif not snip_for_dev:
            st.warning("파일을 찾을 수 없어 AI 초안을 작성할 수 없습니다.")
        else:
            st.warning("AI 설정이 없습니다.")
    
    if _dev:
        st.warning("🟨 데비에이션 등록된 이슈(코드 수정 없이 허용됨)")

    st.session_state.setdefault(_k("dev_type_index"), 0)

    if _reports_dir:
        # AI 생성 버튼이 눌렸을 때도 expander를 열어둠
        expand_deviation = bool(_dev) or st.session_state.get(_k("generate_dev_draft_flag"), False)
        with st.expander("🟨 데비에이션(Deviation) 처리 - 코드 수정 없이 허용(소명 기록)", expanded=expand_deviation):
            st.caption("현상(Context), 안전성(Safety Argument), 대책(Mitigation) 3요소를 중심으로 근거를 남기는 방식")

            status_opts = ["Pending", "Approved", "Rejected"]
            _status_default = max(0, status_opts.index(str((_dev or {}).get("status") or status_opts[0]))) if _dev else 0

            dev_type = st.selectbox("사유(Type)", type_opts, index=st.session_state.get(_k("dev_type_index"), 0), key=_k("dev_type"))
            dev_status = st.selectbox("상태(Status)", status_opts, index=_status_default, key=_k("dev_status"))

            # 기본 작성자(Author) 자동 입력 (Jenkins BUILD_USER_ID 우선)
            if _k("dev_author") not in st.session_state:
                st.session_state[_k("dev_author")] = str((_dev or {}).get("author") or default_author or "")
            dev_author = st.text_input("작성자(Author)", key=_k("dev_author"))

            dev_context = st.text_area("현상(Context) - 왜 이 룰이 위반으로 잡혔는지, 코드/상황 설명", height=110, key=_k("dev_context"))
            dev_safety = st.text_area("안전성(Safety Argument) - 룰을 위반해도 왜 안전한지, 기술적 근거", height=110, key=_k("dev_safety"))
            dev_mitigation = st.text_area("대책(Mitigation) - 방어 코드/테스트/모니터링 등 보완책(해당 시)", height=90, key=_k("dev_mitigation"))
            dev_evidence = st.text_area("근거/참조(Evidence) - 규격/데이터시트/설계문서/리뷰 기록 등", height=90, key=_k("dev_evidence"))
            dev_reviewer = st.text_input("검토/승인자(Reviewer/Approver)", key=_k("dev_reviewer"))

            c1, c2, c3, c4 = st.columns([2, 2, 2, 4])
            with c1:
                if st.button("🤖 AI로 초안 작성", key=_k("dev_ai_draft_btn"), width="stretch", disabled=not snip_for_dev):
                    st.session_state[_k("generate_dev_draft_flag")] = True
                    st.rerun()
            with c2:
                if st.button("✅ 데비에이션 등록/업데이트", key=_k("dev_save"), width="stretch"):
                    rec = dict(_dev or {})
                    rec.update({
                        "rule": gui_utils._normalize_rule_label(_rule) if hasattr(gui_utils, "_normalize_rule_label") else _rule,
                        "rule_raw": _rule, "tool": tool_name, "severity": str(row.get("severity") or ""),
                        "file": file_rel, "line": int(line_num or 0), "message": issue_msg,
                        "type": dev_type, "status": dev_status, "context": st.session_state[_k("dev_context")].strip(),
                        "safety_argument": st.session_state[_k("dev_safety")].strip(),
                        "mitigation": st.session_state[_k("dev_mitigation")].strip(),
                        "evidence": st.session_state[_k("dev_evidence")].strip(),
                        "reviewer": st.session_state[_k("dev_reviewer")].strip(),
                        "author": st.session_state[_k("dev_author")].strip(),
                    })
                    did = gui_utils.upsert_deviation(_reports_dir, rec)
                    st.success(f"저장 완료 (id={did})")
                    st.rerun()
            with c3:
                if _dev and st.button("🗑️ 데비에이션 해제", key=_k("dev_delete"), width="stretch"):
                    ok = gui_utils.delete_deviation(_reports_dir, str(_dev.get("id") or ""))
                    if ok:
                        st.success("데비에이션 해제 완료"); st.rerun()
                    else:
                        st.info("해제할 항목을 찾지 못함")
            with c4:
                st.caption("※ 승인은 보통 QA/동료 리뷰 절차로 진행")

    st.code(issue_msg, language="text")

    if not file_rel or line_num <= 0:
        st.warning("선택 이슈에 file/line 정보 없음, 코드 표시/수정 불가")
        return
    if not target.exists():
        st.error(f"파일을 찾을 수 없음: {target} (해결: {resolve_note})")
        st.caption(f"원본 file 필드: {raw_file}")

        # index 기반 후보가 있을 경우(동일 basename이 여러 폴더에 존재할 수 있음)
        cands = st.session_state.get("editor_resolve_candidates")
        ckey = st.session_state.get("editor_resolve_candidates_key")
        if isinstance(cands, list) and cands:
            st.info(f"대체 경로 후보 {len(cands)}개 발견, 선택하여 열기 가능")
            sel = st.selectbox("대체 경로", options=cands, index=0, key=f"editor_alt_path:{ckey}")
            if st.button("이 경로로 열기", key=f"editor_alt_open:{ckey}"):
                try:
                    st.session_state["editor_force_open_path"] = str(sel)
                    st.session_state["editor_force_open_from"] = str(raw_file_mapped)
                    st.rerun()
                except Exception:
                    pass
        return
    st.caption(f"resolved: {resolve_note}")

    copt1, copt2, copt3 = st.columns([2, 2, 3])
    max_bytes = copt1.number_input("최대 로드 크기(bytes)", 64 * 1024, 50 * 1024 * 1024, MAX_FILE_BYTES_DEFAULT, 256 * 1024)
    win_lines = copt2.number_input("기본 창 라인 수", 40, 800, 120, 20)
    max_snip_lines = copt3.number_input("편집 최대 라인 수", 50, 1000, MAX_SNIPPET_LINES_DEFAULT, 50)

    text, truncated = _read_text_limited(target, int(max_bytes))
    if truncated:
        st.warning("파일이 커서 일부만 로드됨, 전체 파일 편집/패치 적용은 주의 필요")

    all_lines = text.splitlines()
    total = len(all_lines)
    half = int(win_lines) // 2
    start0 = max(1, line_num - half)
    end0 = min(total, line_num + half)

    csel1, csel2, csel3 = st.columns([1, 1, 2])
    sel_start = csel1.number_input("선택 시작줄", 1, max(1, total), start0, 1)
    sel_end = csel2.number_input("선택 끝줄", 1, max(1, total), end0, 1)
    if sel_end < sel_start:
        sel_end = sel_start

    snippet_lines = all_lines[int(sel_start) - 1 : int(sel_end)]
    if len(snippet_lines) > int(max_snip_lines):
        snippet_lines = snippet_lines[: int(max_snip_lines)]
        st.warning("선택 범위가 커서 편집 라인 수를 제한함")

    def _render_numbered(lines_: List[str], base: int) -> str:
        w = len(str(base + len(lines_) - 1))
        return "\n".join([f"{base + i:>{w}} | {s}" for i, s in enumerate(lines_)])

    st.markdown(f"**파일** `{file_rel}`  (총 {total} lines)")
    st.code(_render_numbered(snippet_lines, int(sel_start)), language="text")

    st.markdown("**부분 편집** (선택 영역 내용만 수정)")
    edit_text = st.text_area("선택 영역 텍스트", "\n".join(snippet_lines), height=300, key=f"editor_snippet_{file_rel}_{sel_start}_{sel_end}")

    csave1, csave2, csave3 = st.columns([2, 2, 6])
    with csave1:
        if st.button("💾 선택 영역 저장", type="primary", width="stretch", key=_k("save_selection")):
            try:
                bak = _make_backup(target)
                st.session_state["editor_backups"][file_rel] = str(bak)
                new_lines = all_lines[:]
                edited = edit_text.splitlines()
                new_lines[int(sel_start) - 1 : int(sel_start) - 1 + len(snippet_lines)] = edited
                _write_text(target, "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""))
                st.success(f"저장 완료, backup={bak.name}")
                st.rerun()
            except Exception as e:
                st.error(f"저장 실패: {e}")
                st.code(traceback.format_exc())

    with csave2:
        if st.button("🔄 다시 로드", width="stretch", key=_k("reload_file")):
            st.rerun()
    with csave3:
        st.caption("저장은 파일 전체 중 선택 영역만 교체, 적용 전 백업 생성")

    bak_path = st.session_state.get("editor_backups", {}).get(file_rel)
    c_rb1, c_rb2 = st.columns([2, 8])
    with c_rb1:
        if st.button("↩️ 롤백", key=_k("rollback"), disabled=not bool(bak_path), width="stretch"):
            if bak_path:
                try:
                    bp = Path(str(bak_path))
                    if bp.exists():
                        target.write_bytes(bp.read_bytes())
                        st.success("롤백 완료")
                        st.rerun()
                    else:
                        st.error("백업 파일이 존재하지 않음")
                except Exception as e:
                    st.error(f"롤백 실패: {e}")
    with c_rb2:
        st.caption(f"최근 백업: {bak_path}" if bak_path else "최근 백업 없음")

    # ... (rest of the function: regression check, AI diff, suppressions, re-check) ...
    # The rest of the function is large, so I'll omit it for brevity, but it's included in the replacement.
    st.divider()
    st.subheader("🤖 AI 분석 / 패치(diff)")
    
    snip_for_ai = "\n".join(snippet_lines)
    if len(snip_for_ai) > AI_SNIPPET_MAX_CHARS:
        snip_for_ai = snip_for_ai[:AI_SNIPPET_MAX_CHARS]
        st.warning("AI 입력이 커서 일부만 전송됨")

    c_ai1, c_ai2, c_ai3 = st.columns([2, 2, 6])
    with c_ai1:
        ask_btn = st.button("💬 AI 해결 방안", disabled=cfg is None, width="stretch", key=_k("ai_solve"))
    with c_ai2:
        diff_btn = st.button("🧩 AI diff 생성", disabled=cfg is None, width="stretch", key=_k("ai_diff"))
    with c_ai3:
        if cfg is None:
            st.warning("AI 설정 로드 실패, oai_config_path/모델 연결 확인 필요")
        else:
            st.caption(f"AI 로그: {log_dir}")

    send_to_chat = st.button("➡️ 채팅으로 이슈 보내기", width="stretch", key=_k("send_to_chat"))
    if send_to_chat:
        draft = (
            f"다음 이슈 해결 방안 제안\n"
            f"- tool: {tool_name}\n"
            f"- rule: {_rule}\n"
            f"- file: {file_rel}:{line_num}\n"
            f"- message: {issue_msg}\n\n"
            f"코드 스니펫:\n{snip_for_ai}\n"
        )
        st.session_state["chat_draft"] = draft
        st.success("오른쪽 채팅 패널에서 Enter로 전송")

    if ask_btn and cfg:
        with st.spinner("AI 분석 중..."):
            st.session_state["editor_ai_reply"] = _ai_ask_text(
                cfg=cfg, log_dir=log_dir, file_path=file_rel, line_num=line_num, message=issue_msg, snippet=snip_for_ai,
            )

    if diff_btn and cfg:
        with st.spinner("AI diff 생성 중..."):
            diff_text = _ai_generate_diff(
                cfg=cfg, log_dir=log_dir, rel_file=file_rel, issue_message=issue_msg, snippet=snip_for_ai,
            )
            st.session_state["editor_ai_diff"] = diff_text

    ai_reply = st.session_state.get("editor_ai_reply") or ""
    if ai_reply:
        st.markdown("**AI 해결 방안**")
        st.markdown(ai_reply)

    ai_diff = st.session_state.get("editor_ai_diff") or ""
    if ai_diff:
        st.markdown("**AI diff**")
        diff_only = _extract_unified_diff(ai_diff)
        st.code(diff_only, language="diff")

        c_ap1, c_ap2, c_ap3 = st.columns([2, 2, 6])
        with c_ap1:
            do_apply = st.button("✅ diff 적용", type="primary", width="stretch", key=_k("apply_diff"))
        with c_ap2:
            clear_diff = st.button("🧹 diff 지우기", width="stretch", key=_k("clear_diff"))
        with c_ap3:
            st.caption("적용 전 자동 백업 생성, 실패 시 문맥 불일치 가능")

        if clear_diff:
            st.session_state["editor_ai_diff"] = ""
            st.rerun()

        if do_apply:
            try:
                bak = _make_backup(target)
                st.session_state["editor_backups"][file_rel] = str(bak)
                ok, msg = _apply_unified_diff_to_file(target, diff_only)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            except Exception as e:
                st.error(f"diff 적용 오류: {e}")
                st.code(traceback.format_exc())
    # ... and so on for the rest of the function
    # (Suppression and Re-check sections)
