"""Auto-generate project setup files for UDS/SUTS pipeline.

- component_map.json: SDS DOCX → file→SwCom mapping
- uds_function_swcom_override.json: Reference UDS DOCX → function→SwCom/ASIL/Related mapping
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)


def generate_component_map_from_sds(
    sds_path: str,
    source_root: str,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """SDS 문서에서 component_map.json을 자동 생성한다.

    Args:
        sds_path: SDS DOCX 파일 경로
        source_root: 소스 코드 루트 경로 (콤마 구분 복수 가능)
        output_path: 출력 JSON 경로 (None이면 생성만)

    Returns:
        {"entries": [...], "stats": {...}, "output_path": str}
    """
    from report_gen.requirements import _extract_sds_partition_map

    sds_map = _extract_sds_partition_map(sds_path)
    if not sds_map:
        return {"entries": [], "stats": {"error": "SDS 파싱 실패"}, "output_path": ""}

    # 소스 파일 수집
    roots = [Path(p.strip()).resolve() for p in source_root.replace(";", ",").split(",") if p.strip()]
    source_files: List[Path] = []
    for root in roots:
        if root.exists():
            for f in root.rglob("*.[ch]"):
                if ".svn" not in str(f) and ".git" not in str(f):
                    source_files.append(f)

    # SDS 맵에서 SwCom 정보 추출
    swcom_entries: Dict[str, Dict[str, str]] = {}
    for key, info in sds_map.items():
        asil = info.get("asil", "")
        related = info.get("related", "")
        # SwCom ID 추출
        swcom_match = re.search(r"SwCom[_\s-]*(\d+)", key, re.I)
        if swcom_match:
            swcom_id = f"SwCom_{int(swcom_match.group(1)):02d}"
            swcom_entries[key.lower()] = {
                "component": f"{key}({swcom_id})" if swcom_id not in key else key,
                "swcom_id": swcom_id,
                "asil": asil,
            }

    # 소스 파일 → SwCom 매핑
    entries: List[Dict[str, str]] = []
    matched = 0
    for f in source_files:
        fname = f.name
        fstem = f.stem.lower()
        # SDS 맵에서 파일명/stem으로 매칭
        best_match = None
        best_score = 0
        for sds_key, sds_info in sds_map.items():
            sds_norm = re.sub(r"[^a-z0-9]", "", sds_key.lower())
            file_norm = re.sub(r"[^a-z0-9]", "", fstem.replace("_it_pds", "").replace("_pds", ""))
            if file_norm and sds_norm and (file_norm in sds_norm or sds_norm in file_norm):
                score = min(len(file_norm), len(sds_norm)) / max(len(file_norm), len(sds_norm), 1)
                if score > best_score:
                    best_score = score
                    swcom_m = re.search(r"SwCom[_\s-]*(\d+)", sds_key, re.I)
                    if swcom_m:
                        best_match = {
                            "component": sds_key,
                            "swcom_num": int(swcom_m.group(1)),
                            "asil": sds_info.get("asil", ""),
                        }

        if best_match and best_score >= 0.4:
            sc_num = best_match["swcom_num"]
            comp_name = best_match["component"]
            # 정규화된 component 이름
            if f"SwCom_{sc_num:02d}" not in comp_name:
                comp_name = f"{comp_name}(SwCom_{sc_num:02d})"
            entries.append({
                "file": fname,
                "component": comp_name,
                "structure": str(f.parent.name),
                "verify": "O",
            })
            matched += 1
        else:
            # 매칭 안 되는 파일은 verify=O로 기본 추가 (수동 검토 필요)
            entries.append({
                "file": fname,
                "component": "",
                "structure": str(f.parent.name),
                "verify": "O",
                "_unmapped": True,
            })

    # 출력
    result = {
        "entries": entries,
        "stats": {
            "total_files": len(source_files),
            "matched": matched,
            "unmatched": len(source_files) - matched,
            "swcom_count": len({e["component"] for e in entries if e.get("component")}),
        },
    }

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        # 매핑된 것만 저장 (unmapped 제외)
        mapped_entries = [e for e in entries if not e.get("_unmapped")]
        json.dump(mapped_entries, open(str(out), "w"), indent=2, ensure_ascii=False)
        result["output_path"] = str(out)
        _logger.info("component_map saved: %s (%d entries)", out, len(mapped_entries))

    return result


def generate_override_from_reference_uds(
    uds_path: str,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """레퍼런스 UDS DOCX에서 함수 단위 SwCom/ASIL/Related override 맵을 생성한다.

    Args:
        uds_path: 레퍼런스 UDS DOCX 파일 경로
        output_path: 출력 JSON 경로 (None이면 생성만)

    Returns:
        {"override": {name: {swcom, asil, related}}, "stats": {...}, "output_path": str}
    """
    try:
        import docx
    except ImportError:
        return {"override": {}, "stats": {"error": "python-docx not installed"}, "output_path": ""}

    p = Path(uds_path)
    if not p.exists():
        return {"override": {}, "stats": {"error": f"File not found: {uds_path}"}, "output_path": ""}

    doc = docx.Document(str(p))
    override: Dict[str, Dict[str, Any]] = {}

    for table in doc.tables:
        if not table.rows:
            continue
        first_cell = table.rows[0].cells[0].text.strip()
        if "Function Information" not in first_cell:
            continue

        info: Dict[str, str] = {}
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            label = cells[0]
            val = cells[2] if len(cells) > 2 else cells[-1]
            if label in ("ID", "Name", "ASIL", "Related ID"):
                info[label] = val

        fid = info.get("ID", "")
        name = info.get("Name", "")
        asil = info.get("ASIL", "").strip()
        related = info.get("Related ID", "").strip()

        m = re.match(r"SwUFn_(\d{2})", fid)
        if m and name:
            swcom = int(m.group(1))
            entry: Dict[str, Any] = {"swcom": swcom, "related": related}
            # ASIL 유효성 검증
            if asil and asil.upper() in ("A", "B", "C", "D", "QM"):
                entry["asil"] = asil
            override[name] = entry

    result = {
        "override": override,
        "stats": {
            "total_functions": len(override),
            "with_asil": sum(1 for v in override.values() if v.get("asil")),
            "with_related": sum(1 for v in override.values() if v.get("related")),
            "swcom_count": len({v["swcom"] for v in override.values()}),
        },
    }

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        json.dump(override, open(str(out), "w"), indent=2, ensure_ascii=False)
        result["output_path"] = str(out)
        _logger.info("override saved: %s (%d entries)", out, len(override))

    return result
