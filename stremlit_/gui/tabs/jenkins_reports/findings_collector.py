# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

import gui_utils

from .findings_extractor import (
    _extract_findings_from_prqa_html,
    _extract_findings_from_qac_sur_html,
    _extract_findings_from_text,
    _iter_candidate_text_files,
    _iter_prqa_html_candidates,
    _iter_qac_sur_html_candidates,
    _read_tail,
)
from .utils import _read_json


def _normalize_items(x: Any) -> List[Dict[str, Any]]:
    if isinstance(x, dict) and isinstance(x.get("items"), list):
        return [i for i in x["items"] if isinstance(i, dict)]
    if isinstance(x, list):
        return [i for i in x if isinstance(i, dict)]
    return []


def _maybe_fill_findings_json(rdir: Optional[Path], items: List[Dict[str, Any]]) -> None:
    """reports/findings.json 이 비어있을 때(또는 없음) 합성 이슈로 채움.
    - 원본이 존재하면 .bak 저장 후 덮어씀(캐시 로컬에만 적용)
    - 항상 findings_filled.json도 같이 저장
    """
    if not rdir or not rdir.exists() or not items:
        return
    try:
        filled = rdir / "findings_filled.json"
        filled.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    # auto fill on/off
    try:
        auto_fill = bool(st.session_state.get("auto_fill_findings_json", True))
    except Exception:
        auto_fill = True
    if not auto_fill:
        return

    target = rdir / "findings.json"
    try:
        if target.exists():
            try:
                raw = target.read_text(encoding="utf-8", errors="ignore").strip()
                if raw and raw != "[]":
                    return  # 이미 내용 있음
            except Exception:
                # 읽기 실패면 덮어쓰기 시도는 하지 않음
                return
            # backup
            try:
                bak = rdir / "findings.json.bak"
                if not bak.exists():
                    bak.write_text(raw if raw else "[]", encoding="utf-8")
            except Exception:
                pass
        # write
        target.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _synthesize_findings_from_qac_sur(broot: Optional[Path], rdir: Optional[Path]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for html in _iter_qac_sur_html_candidates(broot, rdir):
        got = _extract_findings_from_qac_sur_html(html)
        if got:
            items.extend(got)
        if len(items) >= 2000:
            break
    return items[:2000]


def _synthesize_findings_for_editor(broot: Optional[Path], rdir: Optional[Path], summary: dict) -> List[Dict[str, Any]]:
    # 0) 캐시 파일 우선
    if rdir and rdir.exists():
        cache = rdir / "findings_synth.json"
        if cache.exists():
            cached = _normalize_items(_read_json(cache, default=None))
            if cached:
                return cached

    items: List[Dict[str, Any]] = []

    # 1) 로그에서 추출
    for p in _iter_candidate_text_files(broot, rdir):
        txt = _read_tail(p)
        if not txt:
            continue
        tool_hint = "log"
        if "cppcheck" in p.name.lower():
            tool_hint = "cppcheck"
        if "clang" in p.name.lower():
            tool_hint = "clang"
        if "prqa" in p.name.lower() or "qac" in p.name.lower():
            tool_hint = "prqa"
        got = _extract_findings_from_text(txt, tool_hint=tool_hint)
        if got:
            items.extend(got)
        if len(items) >= 2000:
            break

    # 2) PRQA HTML에서 추출(가능한 경우)
    if len(items) < 2000:
        for html in _iter_prqa_html_candidates(broot, rdir):
            got = _extract_findings_from_prqa_html(html)
            if got:
                items.extend(got)
            if len(items) >= 2000:
                break

    # dedup
    uniq: List[Dict[str, Any]] = []
    seen: set[tuple] = set()
    for it in items:
        key = (
            str(it.get("tool") or ""),
            str(it.get("file") or ""),
            int(it.get("line") or 0),
            int(it.get("col") or 0),
            str(it.get("rule") or ""),
            str(it.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
        if len(uniq) >= 2000:
            break

    # 캐시 저장
    if rdir and rdir.exists():
        try:
            (rdir / "findings_synth.json").write_text(json.dumps(uniq, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return uniq


def _collect_findings_for_editor(
    broot: Optional[Path],
    rdir: Optional[Path],
    summary: dict,
    *,
    prefer_sur: bool = False,
) -> List[Dict[str, Any]]:
    if prefer_sur:
        items = _synthesize_findings_from_qac_sur(broot, rdir)
        if items:
            return items
    # 1) reports_dir 내 별도 파일 우선(비어있으면 계속)
    if rdir and rdir.exists():
        for name in ("findings.json", "findings_merged.json", "findings_all.json", "issues.json"):
            p = rdir / name
            if p.exists():
                data = _read_json(p, default=None)
                items = _normalize_items(data)
                if items:
                    return items

    # 2) analysis_summary.json 내부 키 fallback
    for k in ("findings", "issues", "items", "all_findings", "merged_findings"):
        items = _normalize_items((summary or {}).get(k))
        if items:
            return items

    # 3) 없으면 합성 생성
    return _synthesize_findings_for_editor(broot, rdir, summary)


def _guess_project_root(broot: Optional[Path], rdir: Optional[Path], summary: dict) -> str:
    # summary에 경로가 있으면 우선 사용
    if isinstance(summary, dict):
        paths = summary.get("paths") or {}
        if isinstance(paths, dict):
            pr = paths.get("project_root") or paths.get("root") or ""
            if pr:
                return str(Path(str(pr)).resolve())
        pr2 = summary.get("project_root") or ""
        if pr2:
            return str(Path(str(pr2)).resolve())

    # build_root 기반 추정
    # SVN checkout 경로 우선(svn_wc)
    if broot:
        basep = Path(broot)
        for rel in (
            "svn_wc",
            "svn_wc/Sources",
            "svn_wc/Sources/APP",
            "svn_wc/Sources/App",
            "svn_wc/source",
            "svn_wc/src",
        ):
            cand = basep / rel
            if cand.exists() and cand.is_dir():
                return str(cand.resolve())

    # Jenkins 캐시에서 소스 스냅샷이 자주 위치하는 경로 후보 우선
    for base in [broot, rdir]:
        if not base:
            continue
        try:
            basep = Path(base)
        except Exception:
            continue
        for rel in (
            "app/PDSM/Sources",
            "app/PDSM/Source",
            "app/PDSM/src",
            "app/Sources",
            "Sources",
            "source",
            "src",
        ):
            cand = basep / rel
            if cand.exists() and cand.is_dir():
                return str(cand.resolve())

    for base in [broot, (broot.parent if broot else None), rdir]:
        if not base:
            continue
        for name in ("workspace", "repo", "source", "src", "project", "code"):
            cand = (Path(base) / name)
            if cand.exists() and cand.is_dir():
                return str(cand.resolve())

    return str((broot or rdir or Path(".")).resolve())


def _collect_source_roots(broot: Optional[Path], rdir: Optional[Path], summary: dict) -> List[str]:
    """Jenkins Viewer에서 코드 루트 후보 수집
    - svn_wc가 있으면 최우선
    - build_root/app/PDSM/Sources 등 스냅샷 경로 후보 포함
    - 중복 제거 후 우선순위 유지
    """
    roots: List[Path] = []

    def add(p: Optional[Path]) -> None:
        if not p:
            return
        try:
            rp = Path(p).resolve()
        except Exception:
            rp = Path(p)
        if rp.exists() and rp.is_dir() and rp not in roots:
            roots.append(rp)

    # 0) summary에 지정된 루트
    if isinstance(summary, dict):
        paths = summary.get("paths") or {}
        if isinstance(paths, dict):
            pr = paths.get("project_root") or paths.get("root") or ""
            if pr:
                add(Path(str(pr)))
        pr2 = summary.get("project_root") or ""
        if pr2:
            add(Path(str(pr2)))

    # 1) svn_wc 우선
    if broot:
        b = Path(broot)
        for rel in (
            "svn_wc",
            "svn_wc/Sources",
            "svn_wc/Sources/APP",
            "svn_wc/Sources/App",
            "svn_wc/src",
            "svn_wc/source",
        ):
            add(b / rel)

    # 2) 스냅샷 후보
    for base in (broot, rdir, (rdir.parent if rdir else None)):
        if not base:
            continue
        bp = Path(base)
        for rel in (
            "app/PDSM/Sources",
            "app/PDSM",
            "app/Sources",
            "Sources",
            "source",
            "src",
        ):
            add(bp / rel)

    # 3) fallback
    add(broot)
    add(rdir)

    # 4) jenkins_scan.json의 자동 추정 루트
    # - app/... 또는 svn_wc/... 형태가 빌드마다 달라질 수 있어 scan 결과를 우선 반영
    try:
        jscan = (summary or {}).get("jenkins_scan") if isinstance(summary, dict) else None
        rels = (jscan or {}).get("source_roots") if isinstance(jscan, dict) else None
        if broot and isinstance(rels, list):
            for rel in rels:
                if not rel:
                    continue
                try:
                    add(Path(broot) / str(rel))
                except Exception:
                    continue
    except Exception:
        pass

    return [str(p) for p in roots]


def _set_editor_open_request(item: Dict[str, Any]) -> None:
    file_path = str(item.get("file") or item.get("path") or "")
    line = item.get("line") or item.get("lineNumber") or 0
    st.session_state["editor_open_file"] = file_path
    st.session_state["editor_open_line"] = int(line) if str(line).isdigit() or isinstance(line, int) else 0
    st.session_state["editor_open_message"] = str(item.get("message") or item.get("msg") or "")
    st.session_state["editor_open_tool"] = str(item.get("tool") or item.get("source") or "jenkins")
    st.session_state["editor_open_severity"] = str(item.get("severity") or item.get("level") or "")
    st.session_state["editor_open_rule"] = str(item.get("rule") or item.get("check") or item.get("id") or "")
    st.session_state["editor_open_kind"] = str(item.get("kind") or item.get("category") or "")
    st.session_state["editor_open_key"] = f"{file_path}:{line}:{datetime.now().strftime('%Y%m%d%H%M%S%f')}"


def _render_findings_editor_bridge(items: List[Dict[str, Any]], broot: Optional[Path] = None, rdir: Optional[Path] = None) -> None:
    st.subheader("🧩 룰 위반/이슈 → Editor 열기")
    if not items:
        st.info("findings/이슈 데이터 미발견, reports_dir에 findings.json 생성 또는 analysis_summary.json에 findings 포함 필요")
        return

    try:
        rule_catalog = gui_utils.load_rule_catalog(Path.cwd(), extra_roots=[p for p in [broot, rdir, (rdir.parent if rdir else None)] if p])
    except Exception:
        rule_catalog = {}

    rows = []
    for it in items:
        f = str(it.get("file") or it.get("path") or "")
        ln = it.get("line") or it.get("lineNumber") or 0
        try:
            ln = int(ln)
        except Exception:
            ln = 0
        if not f or ln <= 0:
            continue
        rows.append(
            {
                "tool": str(it.get("tool") or it.get("source") or ""),
                "severity": str(it.get("severity") or it.get("level") or ""),
                "rule": str(it.get("rule") or it.get("check") or it.get("id") or ""),
                "message": str(it.get("message") or it.get("msg") or ""),
                "file": f,
                "line": ln,
                "_raw": it,
            }
        )

    if not rows:
        st.info("file/line 포함 이슈 없음, Editor 연결 불가")
        return

    df = pd.DataFrame(rows)
    q = st.text_input("검색(rule/message/file)", value="", key="jr_findings_q")
    topn = st.slider("표시 개수(Top N)", min_value=20, max_value=500, value=120, step=20, key="jr_findings_topn")

    dfv = df.copy()
    if q.strip():
        qq = q.strip().lower()
        dfv = dfv[
            dfv["rule"].astype(str).str.lower().str.contains(qq)
            | dfv["message"].astype(str).str.lower().str.contains(qq)
            | dfv["file"].astype(str).str.lower().str.contains(qq)
        ]

    dfv = dfv.sort_values(["severity", "file", "line"], ascending=[True, True, True]).head(int(topn)).reset_index(drop=True)
    st.caption(f"총 {len(df)}개 중 {len(dfv)}개 표시")

    for i, r in dfv.iterrows():
        c1, c2 = st.columns([1, 9])
        with c1:
            if st.button("🧩 열기", key=f"jr_open_{i}"):
                _set_editor_open_request(r["_raw"] if isinstance(r.get("_raw"), dict) else r.to_dict())
                st.session_state["_jr_view_mode_next"] = "🧩 Editor"
                st.success("Editor 보기로 전환됨, 선택 이슈 핀 고정됨")
                st.rerun()
        with c2:
            rule_id = str(r.get("rule") or "")
            description = gui_utils.rule_desc(rule_id, rule_catalog)
            st.caption(f"[{r.get('tool')}/{r.get('severity')}] {r.get('file')}:{int(r.get('line') or 0)}")

            if rule_id:
                st.text_input(
                    "Rule",
                    value=rule_id,
                    key=f"jr_finding_rule_tooltip_{i}",
                    disabled=True,
                    help=description or "설명 없음",
                    label_visibility="collapsed",
                )

            msg = str(r.get("message") or "")
            if msg:
                st.code(msg, language="text")


__all__ = [
    "_normalize_items",
    "_maybe_fill_findings_json",
    "_synthesize_findings_from_qac_sur",
    "_synthesize_findings_for_editor",
    "_collect_findings_for_editor",
    "_guess_project_root",
    "_collect_source_roots",
    "_set_editor_open_request",
    "_render_findings_editor_bridge",
]
