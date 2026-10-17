"""Auto-generate project setup files for UDS/SUTS pipeline.

- component_map.json: SDS DOCX → file→SwCom mapping
- uds_function_swcom_override.json: Reference UDS DOCX → function→SwCom/ASIL/Related mapping

(R97) 맵은 이제 프로젝트 폴더(`docs/project_maps/<프로젝트>/`, `report_gen.project_maps`)에 쓴다 — 쓰기는 라우터
(`/api/local/project-setup/*`)가 `project_maps.write_project_map` 으로 한다. component_map 은 SDS 의 **소프트웨어 구조 표**
(`component_map_from_structure_table`)를 먼저 읽고, 그 표가 없을 때만 옛 파티션 이름 퍼지 매칭(`generate_component_map_from_sds`)
으로 간다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from report_gen.source_roots import split_source_roots

_logger = logging.getLogger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
#: 구조 표 Layer 칸의 파일 이름 토큰 — `Ap_DoorCtrl_it.PDS.h`(HD 표의 오기)처럼 점이 낀 이름도 한 토큰이다.
_FILE_TOKEN = re.compile(r"[A-Za-z_][\w\-]*(?:\.[A-Za-z_][\w\-]*)*\.(?:c|h)\b", re.I)
_SKIP_DIRS = {".svn", ".git"}


def _cell_text(tc: Any) -> str:
    return "\n".join("".join(t.text or "" for t in p.iter(f"{_W}t")) for p in tc.iter(f"{_W}p"))


def _tc_span(tc: Any) -> int:
    pr = tc.find(f"{_W}tcPr")
    gs = pr.find(f"{_W}gridSpan") if pr is not None else None
    try:
        return max(1, int(gs.get(f"{_W}val"))) if gs is not None else 1
    except (TypeError, ValueError):
        return 1


def _tc_continues(tc: Any) -> bool:
    """세로 병합의 **이어지는** 칸 — `w:vMerge` 가 있고 `val=restart` 가 아니다(값은 위 칸의 것)."""
    pr = tc.find(f"{_W}tcPr")
    vm = pr.find(f"{_W}vMerge") if pr is not None else None
    return vm is not None and vm.get(f"{_W}val") != "restart"


def _header_cells(tr: Any) -> List[str]:
    out: List[str] = []
    for tc in tr.findall(f"{_W}tc"):
        out.extend([" ".join(_cell_text(tc).split())] * _tc_span(tc))
    return out


def _is_structure_header(head: List[str]) -> bool:
    return bool(head) and head[0].lower().startswith("layer") and any("component" in h.lower() for h in head)


def _find_structure_table(docx_path: str) -> Any:
    """SDS 의 소프트웨어 구조 표(머리 행 `Layer1 … Component Name`) — 없으면 None.

    ⚠ python-docx 로 열지 않는다 — SwDS 는 50MB 급이고 python-docx 의 Document 는 GC 전까지 남는다(1.2GB 실측). 본문
    XML 만 lxml `iterparse` 로 표 단위로 훑고, 본문 직속 표는 보고 나면 비운다(중첩 표는 바깥 표와 함께 비운다).
    """
    from lxml import etree

    with zipfile.ZipFile(docx_path) as z, z.open("word/document.xml") as fh:
        for _ev, tbl in etree.iterparse(fh, events=("end",), tag=f"{_W}tbl", huge_tree=True):
            rows = tbl.findall(f"{_W}tr")
            if rows and _is_structure_header(_header_cells(rows[0])):
                return tbl
            parent = tbl.getparent()
            if parent is not None and parent.tag == f"{_W}body":
                tbl.clear()
                while tbl.getprevious() is not None:
                    del parent[0]
    return None


def _walk_local(root: Path) -> Iterable[Path]:
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in _SKIP_DIRS]
        for fn in fns:
            yield Path(dp) / fn


def _norm_dir(text: str) -> str:
    """폴더 · 구조 이름 대조용 — 소문자, 영숫자만(`Generated_Code` ↔ `Generated_ Code` ↔ `generatedcode`)."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _rel_parts(path: Path, root: Path) -> List[str]:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return [str(x) for x in rel.parts[:-1]]


def _path_key(path: Path, root: Path) -> str:
    """경로 키 — `<루트 폴더 이름>/<루트 상대 경로>`(`NE1AW_PORTING/Generated_Code/EEPROM.c`). 조회는 `endswith` 로 맞춘다."""
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
    return f"{root.name}/{rel}" if root.name else rel


def component_map_from_structure_table(
    sds_path: str,
    source_root: str,
    *,
    walk: Optional[Callable[[Path], Iterable[Path]]] = None,
) -> Dict[str, Any]:
    """SDS 소프트웨어 구조 표 → component_map 행 + 대조 통계. (R97)

    규칙:
      · 머리 행이 `Layer…` 로 시작하고 `Component Name` 칸이 있는 표. Layer 칸의 `*.c`/`*.h` 토큰마다 그 행의 컴포넌트.
      · 세로 병합의 이어지는 칸(`w:vMerge`, `val=restart` 아님)은 위 칸 값을 잇는다 — 컴포넌트 · 구조 이름만. 파일 토큰은 잇지
        않는다(병합 칸의 파일은 첫 행에 한 번만 적힌다).
      · `structure` = 파일 토큰이 없는 가장 깊은 Layer 칸(Layer3 아니면 Layer2), `component` = `Component Name`(라벨은
        `Name(SwCom_NN)` 로 정규화). 표가 컴포넌트를 비운 행(`Lib` · `Project Header`)은 구조 이름을 컴포넌트로 쓴다 —
        HDPDM01 수기 맵이 같은 관례(`Project Header`)였다. 그런 행 수는 `component_from_structure` 로 센다.
      · 행은 **소스 트리에 있는 파일만**, `verify="O"`. 이름 비교는 대소문자 무시, 행의 `file` 은 소스의 철자(조회가 철자를 본다).
      · (R97 리뷰 W8a) 같은 이름이 소스 여러 곳에 있으면(KJPDS02_PV `EEPROM.c`: APP `Generated_Code` · FBL `Sources/Eeprom`)
        이름만으로 고르지 않는다 — 표가 적은 구조 이름(`Generated_Code`)이 경로 폴더에 있는 사본에만 **경로 키 행**
        (`match: "path"` — 이름 · stem 키를 등록하지 않는다)을 만들고, 나머지 사본은 행 없이 `twins_left_unmapped` 로 낸다.
        어느 사본도 구조 이름과 안 맞으면 `twins_unresolved`(행 없음).
      · (R97 리뷰 W8b) 표에 있는데 소스에 없는 파일 → `table_files_not_in_source`(문서 결함 후보 — HD 8 · PV 4 실측). 비슷한
        소스 이름이 있으면 `table_files_not_in_source_hints` 로 **알려 주기만** 한다(자동 대응 금지 — `SysDiag_PDS.c` 와
        `SysDiagCtrl_PDS.c` 가 같은 파일인지는 문서 작성자가 정한다).
      · 소스에 있는데 표에 없는 파일 → `source_files_not_listed` 로 **세기만** 한다. 행도 X 도 만들지 않는다 — 문서가 면제
        근거를 주지 않는다(HDPDM01 의 X 49행은 사람이 정한 것이다, 커밋 49558d3a).
      · 한 파일이 서로 다른 컴포넌트 두 행에 있으면 고르지 않는다 — 행을 만들지 않고 `conflicting_files` 로 낸다.
      · (R97 리뷰 W9) 문서를 열 수 없으면(.docx 가 아님 · 본문 XML 손상) 예외 대신 `found=False` + `error` — 호출자가 옛 판정으로
        폴백하고 그 사실을 말한다.

    Returns:
        `{"found": bool, "rows": [...], "stats": {...}}`(+ 못 읽었으면 `error`). 표가 없으면 `found=False` · 빈 행.
    """
    import difflib

    from lxml import etree

    from report_gen.utils import _normalize_swcom_label

    try:
        tbl = _find_structure_table(sds_path)
    except (zipfile.BadZipFile, KeyError, OSError, etree.XMLSyntaxError) as exc:
        _logger.warning("SDS 구조 표를 읽지 못했다 %s: %s", Path(sds_path).name, exc)
        why = f"{type(exc).__name__}: {str(exc)[:160]}"
        return {"found": False, "rows": [], "error": why,
                "stats": {"reason": f"SDS 를 구조 표로 읽지 못했다({why}) — .docx 가 아니거나 본문이 손상됐다"}}
    if tbl is None:
        return {"found": False, "rows": [], "stats": {"reason": "SDS 에 소프트웨어 구조 표(Layer1 … Component Name)가 없다"}}
    rows = tbl.findall(f"{_W}tr")
    head = _header_cells(rows[0])
    ncols = len(head)
    comp_col = next(i for i, h in enumerate(head) if "component" in h.lower())
    carry = [""] * ncols
    # 소문자 이름 → {name, components: {comp: structure}, dirs: {comp: 구조 이름 후보(정규화)}}
    table: Dict[str, Dict[str, Any]] = {}
    for tr in rows[1:]:
        own = [""] * ncols
        eff = [""] * ncols
        col = 0
        for tc in tr.findall(f"{_W}tc"):
            if col >= ncols:
                break
            span = _tc_span(tc)
            cont = _tc_continues(tc)
            text = "" if cont else _cell_text(tc)
            for c in range(col, min(col + span, ncols)):
                own[c] = text
                eff[c] = carry[c] if cont else text
                carry[c] = eff[c]
            col += span
        layer_cols = [c for c in range(ncols) if c != comp_col]
        tokens = [tok for c in layer_cols for tok in _FILE_TOKEN.findall(own[c])]
        if not tokens:
            continue
        # 칸 안 줄바꿈은 공백으로 잇되, `_` 뒤 줄바꿈은 이름이 접힌 것이다(PV 표 `Generated_` / `Code` = 폴더 `Generated_Code`)
        names = [re.sub(r"(?<=_)\s+", "", " ".join(eff[c].split())) for c in layer_cols
                 if eff[c].strip() and not _FILE_TOKEN.search(eff[c])]
        structure = names[-1] if names else ""
        component = _normalize_swcom_label(" ".join(eff[comp_col].split())) or structure
        for tok in tokens:
            rec = table.setdefault(tok.lower(), {"name": tok, "components": {}, "dirs": {}, "from_structure": False})
            rec["components"].setdefault(component, structure)
            rec["dirs"].setdefault(component, {_norm_dir(n) for n in names if _norm_dir(n)})
            if not " ".join(eff[comp_col].split()):
                rec["from_structure"] = True

    # 소스 파일 — 이름(소문자) → [(실제 경로, 루트)]
    walker = walk or _walk_local
    src_by_lower: Dict[str, List[Any]] = {}
    src_total = 0
    for raw_root in split_source_roots(source_root):
        root = Path(raw_root)
        for p in walker(root):
            if p.suffix.lower() not in (".c", ".h") or any(part in _SKIP_DIRS for part in p.parts):
                continue
            src_total += 1
            src_by_lower.setdefault(p.name.lower(), []).append((p, root))

    out_rows: List[Dict[str, str]] = []
    not_in_source: List[str] = []
    hints: Dict[str, List[str]] = {}
    conflicting: Dict[str, List[str]] = {}
    twins_path_keyed: Dict[str, List[str]] = {}
    twins_left: Dict[str, List[str]] = {}
    twins_unresolved: Dict[str, List[str]] = {}
    from_structure = 0
    for low, rec in sorted(table.items()):
        if low not in src_by_lower:
            not_in_source.append(rec["name"])
            close = difflib.get_close_matches(low, list(src_by_lower), n=3, cutoff=0.8)
            if close:
                hints[rec["name"]] = sorted({p.name for c in close for p, _r in src_by_lower[c]})
            continue
        comps = rec["components"]
        if len(comps) > 1:
            conflicting[rec["name"]] = sorted(comps)
            continue
        (component, structure), = comps.items()
        from_structure += 1 if rec["from_structure"] else 0
        copies = src_by_lower[low]
        if len(copies) == 1:
            out_rows.append({"structure": structure, "file": copies[0][0].name, "component": component, "verify": "O"})
            continue
        # 같은 이름이 여러 곳 — 표가 적은 구조 이름이 경로 폴더에 있는 사본만
        want = rec["dirs"].get(component) or set()
        hit = [(p, r) for p, r in copies if want & {_norm_dir(x) for x in _rel_parts(p, r)}]
        if hit and len(hit) < len(copies):
            twins_path_keyed[rec["name"]] = [_path_key(p, r) for p, r in hit]
            twins_left[rec["name"]] = [_path_key(p, r) for p, r in copies if (p, r) not in hit]
            for p, r in hit:
                out_rows.append({"structure": structure, "file": _path_key(p, r), "component": component,
                                 "verify": "O", "match": "path"})
        else:
            # 다 맞거나(구조 이름이 두 트리에 다 있다) 아무것도 안 맞는다 — 어느 사본인지 표가 말하지 않는다
            twins_unresolved[rec["name"]] = [_path_key(p, r) for p, r in copies]
    listed_src = sum(len(v) for low, v in src_by_lower.items() if low in table)
    unlisted = sorted(str(p) for low, v in src_by_lower.items() if low not in table for p, _r in v)
    stats = {
        "method": "structure_table",
        "table_files": len(table),
        "matched": len(out_rows),                    # 쓴 행 수(옛 화면 토스트 키와 같은 이름)
        "table_files_in_source": len(table) - len(not_in_source),
        "table_files_not_in_source": not_in_source,
        "table_files_not_in_source_hints": hints,
        "conflicting_files": conflicting,
        "component_from_structure": from_structure,
        "source_files": src_total,
        "source_files_listed": listed_src,
        "source_files_not_listed": len(unlisted),
        "source_files_not_listed_sample": unlisted[:20],
        "twins_path_keyed": twins_path_keyed,
        "twins_left_unmapped": twins_left,
        "twins_unresolved": twins_unresolved,
        "swcom_count": len({r["component"] for r in out_rows}),
    }
    return {"found": True, "rows": out_rows, "stats": stats}


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
    roots = [Path(p).resolve() for p in split_source_roots(source_root)]
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
        # (R97) UTF-8 명시 — 예전 `open(out, "w")` 는 Windows 로케일(cp949)로 써서 utf-8 로 읽는 쪽과 어긋났고 핸들을 닫지 않았다
        out.write_text(json.dumps(mapped_entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
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
        out.write_text(json.dumps(override, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")   # (R97) UTF-8
        result["output_path"] = str(out)
        _logger.info("override saved: %s (%d entries)", out, len(override))

    return result
