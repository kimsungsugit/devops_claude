# /app/gui/tabs/knowledge.py
# -*- coding: utf-8 -*-
# Knowledge Base Viewer (v30.8: entry-level delete)

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict, Any, Tuple

import pandas as pd
import streamlit as st

import config
import ui_common


def _load_entries(kb_dir: Path) -> List[Dict[str, Any]]:
    """Load KB entries.

    Supports:
    - One entry per file (dict)
    - Multiple entries per file (list[dict])

    Adds internal fields:
    - _file, _path
    - _entry_index (index within list; 0 for dict)
    - _file_is_list (True if source file was list)
    - _entry_key (unique key: <filename>#<index>)
    """
    entries: List[Dict[str, Any]] = []
    if not kb_dir.exists():
        return entries

    for fp in sorted(kb_dir.glob("*.json"), key=lambda p: p.name):
        if fp.name.endswith(".tmp") or fp.name.endswith(".bak"):
            continue
        try:
            txt = fp.read_text(encoding="utf-8")
            if not txt.strip():
                continue
            obj = json.loads(txt)

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
                if "id" not in d or not str(d.get("id") or "").strip():
                    d["id"] = fp.stem
                entries.append(d)
        except Exception as e:
            ui_common.log_exception(f"KB 로드 실패: {fp.name}", e)
            continue
    return entries


def _atomic_write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _delete_entry(row: Dict[str, Any]) -> Tuple[bool, str]:
    """Delete a single entry. Returns (ok, message)."""
    try:
        path = Path(str(row.get("_path") or ""))
        if not path.exists():
            return False, "파일이 이미 없음"

        idx = int(row.get("_entry_index") or 0)
        is_list = bool(row.get("_file_is_list"))

        try:
            obj = json.loads(path.read_text(encoding="utf-8", errors="ignore") or "")
        except Exception:
            obj = None

        if is_list and isinstance(obj, list):
            if idx < 0 or idx >= len(obj):
                return False, "엔트리 인덱스가 유효하지 않음"
            new_list = [x for i, x in enumerate(obj) if i != idx]
            if not new_list:
                path.unlink(missing_ok=True)
                return True, "파일이 비어 삭제됨"
            _atomic_write_json(path, new_list)
            return True, "엔트리 1개 삭제됨"

        # dict 파일은 파일 자체 삭제
        path.unlink(missing_ok=True)
        return True, "파일(단일 엔트리) 삭제됨"
    except Exception as e:
        return False, f"삭제 중 오류: {type(e).__name__}"


def render_knowledge_base(project_root: str, report_dir: str) -> None:
    root = Path(project_root).resolve()
    kb_dir_name = getattr(config, "KB_DIR_NAME", "kb_store")
    kb_dir = root / report_dir / kb_dir_name

    st.subheader("📚 Knowledge Base (RAG Store)")

    if not kb_dir.exists():
        st.info(f"지식 베이스 디렉터리 없음: `{kb_dir}`")
        return

    entries = _load_entries(kb_dir)
    if not entries:
        st.info("현재 저장된 RAG 엔트리가 없음")
        return

    df = pd.DataFrame(entries)
    st.write(f"총 엔트리 수: **{len(df)}**")
    if "timestamp" in df.columns and not df["timestamp"].dropna().empty:
        try:
            st.write(f"최근 업데이트: `{df['timestamp'].astype(str).max()}`")
        except Exception:
            pass

    # 간단 필터: error_clean / tags 기준 검색
    search_text = st.text_input("에러/메시지 검색", "")
    if search_text:
        q = str(search_text)
        mask = df.get("error_clean", "").astype(str).str.contains(q, case=False, na=False)
        df = df[mask]

    show_cols = [c for c in ["id", "error_clean", "tags", "timestamp", "_file"] if c in df.columns]
    st.dataframe(df[show_cols].fillna(""), width="stretch", height=320, hide_index=True)

    st.markdown("---")
    st.markdown("### 세부 엔트리 확인 및 삭제(엔트리 단위)")

    # choose by internal key to avoid duplicate 'id'
    options = df[["_entry_key", "id", "_file", "_entry_index"]].to_dict("records")
    def _fmt(o: Dict[str, Any]) -> str:
        return f"{o.get('id')} | {o.get('_file')}#{o.get('_entry_index')}"

    pick = st.selectbox("엔트리 선택", options=options, format_func=_fmt)
    if not pick:
        return

    row = df[df["_entry_key"] == pick["_entry_key"]].iloc[0].to_dict()

    st.json(
        {
            "id": row.get("id"),
            "error_raw": row.get("error_raw"),
            "error_clean": row.get("error_clean"),
            "fix": row.get("fix"),
            "tags": row.get("tags"),
            "timestamp": row.get("timestamp"),
            "source_file": row.get("source_file", row.get("_file")),
        }
    )

    st.caption(f"원본: `{row.get('_path')}` (entry_index={row.get('_entry_index')})")

    if st.button("🗑️ 선택 엔트리 삭제", type="primary"):
        ok, msg = _delete_entry(row)
        if ok:
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)
