# /app/workflow/rag.py
# -*- coding: utf-8 -*-
# RAG Knowledge Base (v30.4: directory-backed, atomic writes)

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

try:  # optional HTTP embedder
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

import config


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _normalize_message(msg: str) -> str:
    msg = msg or ""
    # 컴파일 로그 등의 노이즈 제거
    msg = re.sub(r"/app/[^\s]+", "<PATH>", msg)
    msg = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z", "<TIME>", msg)
    msg = re.sub(r"\s+", " ", msg)
    return msg.strip()


class KnowledgeBase:
    """
    디렉터리 기반 RAG 저장소

    - base_dir/ 아래에 여러 개의 JSON 엔트리 파일 생성
      예) kb_store/kb_20251203T075959123456Z.json
    - 각 파일에는 단일 dict 엔트리 저장
    - 저장 시 항상 tmp 파일에 먼저 쓰고 rename 으로 교체
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.data: List[Dict[str, Any]] = []
        self._load_all()

    # ---------------- 내부 유틸 ----------------

    def _iter_entry_files(self):
        for p in self.base_dir.glob("*.json"):
            if p.name.endswith(".tmp") or p.name.endswith(".bak"):
                continue
            yield p

    def _write_atomic(self, path: Path, payload: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _ensure_shape(self, raw: Dict[str, Any], source_file: str) -> Dict[str, Any]:
        d = dict(raw)
        error_raw = str(d.get("error_raw", ""))
        error_clean = _normalize_message(d.get("error_clean") or error_raw)
        d["error_raw"] = error_raw
        d["error_clean"] = error_clean
        d["fix"] = str(d.get("fix", ""))
        tags = d.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]
        d["tags"] = [str(t) for t in tags]
        role = d.get("role")
        d["role"] = str(role) if role is not None else None
        stage = d.get("stage")
        d["stage"] = str(stage) if stage is not None else None
        context = d.get("context")
        d["context"] = str(context) if context is not None else ""
        vec = d.get("vector") or []
        if isinstance(vec, list):
            d["vector"] = [float(x) for x in vec]
        else:
            d["vector"] = []
        d["weight"] = float(d.get("weight", 1.0))
        d["apply_count"] = int(d.get("apply_count", 0))
        d["timestamp"] = d.get("timestamp") or datetime.utcnow().isoformat()
        d["source_file"] = source_file
        if "id" not in d:
            d["id"] = os.path.splitext(os.path.basename(source_file))[0]
        return d

    def _load_all(self) -> None:
        # 1) 레거시 단일 JSON 파일 → 디렉터리로 마이그레이션 (최초 1회)
        legacy = self.base_dir.parent / "knowledge_base.json"
        has_entries = any(True for _ in self._iter_entry_files())
        if legacy.exists() and not has_entries:
            try:
                raw = json.loads(legacy.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    raw = raw.get("data") or raw.get("entries") or []
                if isinstance(raw, list):
                    for idx, ent in enumerate(raw):
                        if not isinstance(ent, dict):
                            continue
                        tmp = self._ensure_shape(ent, f"legacy_{idx}.json")
                        self._append_new_entry(tmp, write_to_disk=True)
                # 백업 후 원본 rename
                legacy.rename(legacy.with_suffix(legacy.suffix + ".bak"))
            except Exception:
                # 실패해도 그냥 무시, 이후 현재 디렉터리만 사용
                pass

        # 2) 디렉터리 내 엔트리 로드
        self.data.clear()
        for fp in sorted(self._iter_entry_files(), key=lambda p: p.name):
            try:
                txt = fp.read_text(encoding="utf-8")
                if not txt.strip():
                    continue
                obj = json.loads(txt)
                if isinstance(obj, list):
                    objs = obj
                else:
                    objs = [obj]
                for ent in objs:
                    if not isinstance(ent, dict):
                        continue
                    shaped = self._ensure_shape(ent, fp.name)
                    self.data.append(shaped)
            except Exception:
                # 손상된 파일은 건너뛰기
                continue

    def _new_id(self) -> str:
        return "kb_" + datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")

    def _append_new_entry(self, entry: Dict[str, Any], write_to_disk: bool = True) -> None:
        if "id" not in entry:
            entry["id"] = self._new_id()
        file_name = entry.get("source_file") or f"{entry['id']}.json"
        entry["source_file"] = file_name
        if write_to_disk:
            path = self.base_dir / file_name
            self._write_atomic(path, entry)
        self.data.append(entry)

    def _get_embedding(self, text: str) -> List[float]:
        text = text.strip()
        if not text:
            return []
        # 1) 외부 임베딩 API 사용 시
        if requests is not None and os.environ.get("KB_EMBED_URL"):
            try:
                resp = requests.post(
                    os.environ["KB_EMBED_URL"],
                    json={"text": text},
                    timeout=5,
                )
                resp.raise_for_status()
                vec = resp.json().get("vector") or []
                return [float(v) for v in vec]
            except Exception:
                # 실패 시 로컬 fallback
                pass
        # 2) 로컬 난수 기반 임베딩 (동일 입력 → 동일 벡터 위해 seed 고정)
        seed = abs(hash(text)) % (2**32)
        rng = np.random.default_rng(seed)
        return rng.normal(size=64).astype(float).tolist()

    # ---------------- 퍼블릭 API ----------------

    def search(
        self,
        error_msg: str,
        top_k: int = 3,
        *,
        tags: Optional[List[str]] = None,
        role: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        에러 메시지를 기반으로 과거 성공 패턴 검색
        """
        if not self.data:
            return []

        query = _normalize_message(error_msg)
        if not query:
            return []

        q_vec = np.array(self._get_embedding(query), dtype=float)
        if q_vec.size == 0:
            return []

        norm_tags = [str(t) for t in (tags or []) if str(t).strip()]
        role = str(role) if role else None
        stage = str(stage) if stage else None

        results: List[Dict[str, Any]] = []
        for idx, ent in enumerate(self.data):
            v = ent.get("vector") or self._get_embedding(ent["error_clean"])
            v_arr = np.array(v, dtype=float)
            score = _cosine(q_vec, v_arr) * float(ent.get("weight", 1.0))
            if role and ent.get("role") == role:
                score += 0.15
            if stage and ent.get("stage") == stage:
                score += 0.1
            if norm_tags:
                ent_tags = set(ent.get("tags") or [])
                hit = len(ent_tags.intersection(norm_tags))
                if hit:
                    score += 0.05 * hit
            if score <= 0.0:
                continue
            item = dict(ent)
            item["index"] = idx
            item["score"] = score
            results.append(item)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def learn(
        self,
        error_msg: str,
        fix_pattern: str,
        tags: Optional[List[str]] = None,
        success: bool = True,
        *,
        role: Optional[str] = None,
        stage: Optional[str] = None,
        context: Optional[str] = None,
    ) -> None:
        """
        성공한 수정 패턴을 지식 베이스에 저장
        """
        if not success:
            # 실패한 패턴은 기본적으로 저장하지 않음
            return

        ctx = _normalize_message(error_msg)
        if not ctx:
            return

        # 중복 패턴 간단 필터링 (동일 error_clean + 유사 fix)
        for ent in self.data:
            if ent.get("error_clean") == ctx and ent.get("fix") == fix_pattern:
                if role and ent.get("role") not in (None, role):
                    continue
                if stage and ent.get("stage") not in (None, stage):
                    continue
                # 이미 동일 패턴 존재 → weight만 조금 올리고 종료
                ent["weight"] = float(ent.get("weight", 1.0)) + 0.1
                path = self.base_dir / ent["source_file"]
                self._write_atomic(path, ent)
                return

        vec = self._get_embedding(ctx)
        entry: Dict[str, Any] = {
            "id": self._new_id(),
            "error_raw": error_msg,
            "error_clean": ctx,
            "fix": fix_pattern,
            "tags": tags or [],
            "role": str(role) if role else None,
            "stage": str(stage) if stage else None,
            "context": str(context) if context else "",
            "vector": vec,
            "weight": 1.0,
            "apply_count": 1,
            "timestamp": datetime.utcnow().isoformat(),
            "source_file": "",  # _append_new_entry 에서 채움
        }
        self._append_new_entry(entry, write_to_disk=True)

    def feedback(self, index: int, positive: bool = True) -> None:
        """
        나중에 UI에서 thumbs-up/down 같은 피드백 연결용 훅
        """
        if index < 0 or index >= len(self.data):
            return
        ent = self.data[index]
        delta = 0.2 if positive else -0.2
        ent["weight"] = max(0.1, float(ent.get("weight", 1.0)) + delta)
        ent["apply_count"] = int(ent.get("apply_count", 0)) + (1 if positive else 0)
        path = self.base_dir / ent["source_file"]
        self._write_atomic(path, ent)


def get_kb(report_dir: Path) -> KnowledgeBase:
    """
    report_dir 기준 RAG 저장소 인스턴스 반환

    기존: report_dir / "knowledge_base.json"
    변경: report_dir / config.KB_DIR_NAME (디렉터리)
    """
    kb_dir_name = getattr(config, "KB_DIR_NAME", "kb_store")
    base_dir = Path(report_dir) / kb_dir_name
    return KnowledgeBase(base_dir)
