"""프로젝트 맵 — 저장소에 둔 **프로젝트 고유 자료**를 그 프로젝트의 생성에만 쓴다 (R97, 2026-10-17).

## 왜 이 모듈이 생겼나

저장소 `docs/` 에 프로젝트 고유 파일 둘이 놓여 **모든 프로젝트에** 파일 · 함수 이름으로 적용되고 있었다:

- `docs/component_map.json` — 파일 → SwCom 라벨 · 시험 범위(`verify` O/X). HDPDM01(PDS64) 자료다: 경로 키가
  `PDS64_FBL/…` · `PDS64_RD_LIN/…` 이고, verify=X 49행은 사람이 정한 것이다(커밋 49558d3a — LIN 스택 드라이버 · 시동 코드
  · FBL Lib).
- `docs/uds_function_swcom_override.json` — 함수 → SwCom · Related · ASIL(251개). 이것도 **HDPDM01** 자료다(2026-10-17 실측:
  HD SwUDS v1.07 대비 이름 251/251 · ASIL 250/250 · Related 245/251, KJPDS02_PV SwUDS v3.03 대비 이름 223 · ASIL 220/222 ·
  Related 190). 주석 · 공시 · 계획서 P7 이 "KJPDS02 스냅샷" 이라 적어 온 것은 **틀린 귀속**이다.

그래서 KJPDS02_PV 를 만들면 HD 의 맵이 걸렸다 — PV 소스 178 파일 중 110 이 이름으로 맞고 그중 35 가 verify=X(그 파일이 정의한
115 함수 중 PV SwUDS 가 설계한 25 개 — FBL `lin.c` 24 + `lin_lld_sci_init` — 가 문서 범위 밖으로 빠졌다), override 는 PV 함수
223 개에 HD 의 Related · ASIL 을 줬다. HDPDM01 자신의 산출물은 맞다 — 이 모듈은 그 결과를 바꾸지 않는다(같은 바이트를 옮겼다).

## 저장 구조

```
docs/project_maps/<key>/project.json                       매니페스트(아래)
docs/project_maps/<key>/component_map.json                  [{structure, file, component, verify}] — 옛 형식 그대로
docs/project_maps/<key>/uds_function_swcom_override.json    {function: {swcom, related, asil}} — 옛 형식 그대로
```

매니페스트: `{"schema": 1, "scm_id": "...", "project": "...", "source_roots": [...],
"maps": {"component_map": {"file": "component_map.json", "origin": "..."}, "override": {"file": "...", "origin": "..."}}}`.

## 판정 (fail-closed)

1. `scm_id` 를 주면 그 id 의 매니페스트(대소문자 무시) — **정확히 하나**일 때만. 단 (R97 리뷰2 W1) 생성 루트가 있는데 그
   매니페스트 루트에 안 들면 맵을 쓰지 않고 **루트 경로와 똑같이** 판정한다(+ `roots_moved` 문제 · 루트 재등록 안내) — id 경로
   (준비 게이트 · 측정 · 영향 분석 재생성)와 루트 경로(문서 생성 허브)가 같은 입력에서 다른 맵을 쓰면 게이트가 잰 문서와 만든
   문서가 갈린다. 그래서 id 는 루트가 둘 이상의 매니페스트에 맞을 때 고르는 데(모호 해소) · 루트가 없을 때 쓴다. Jenkins 캐시
   체크아웃 루트(`.devops_pro_cache/…`)는 매니페스트 루트에 들지 않으므로 id 를 줘도 맵을 쓰지 않는다(루트 경로와 같은
   결론) — 체크아웃에도 맵을 걸려면 관리자가 그 루트를 매니페스트에 등록해야 한다.
2. 아니면 생성 루트 R 과 매니페스트 루트 M 을 **레지스트리 조회와 같은 정규화**(`source_roots.normalize_root_key`)로 맞춰,
   R 이 비어 있지 않고 R ⊆ M 인 매니페스트가 정확히 하나일 때만 그 프로젝트다. 둘 이상이면 `ambiguous` — 고르지 않는다.
3. 프로젝트가 정해져도 그 종류의 맵을 등록하지 않았으면 `none`. 맵 파일을 못 읽거나 형식이 틀리면 `invalid`(쓰지 않는다).
4. 프로젝트가 안 정해졌는데 다른 프로젝트가 그 종류의 맵을 갖고 있으면 `not_this_project` — 예전처럼 이름으로 걸었다면
   남의 맵이 걸렸을 자리다. 화면이 "이 프로젝트의 SDS 로 맵을 만들라" 고 안내한다.
5. 옛 루트 파일(`docs/component_map.json` · `docs/uds_function_swcom_override.json`)은 **어떤 경우에도 읽지 않는다**.

지문(`ProjectMaps.fingerprint`)은 종류마다 `status:project:sha1`(실제로 읽은 바이트의 sha1) — 소스 단계 캐시 키 · 서명에 들어가
맵을 고치면 캐시가 깨진다.

⚠ 모듈 수준에서 `backend` 를 import 하지 않는다 — 생성기 · 단발 스크립트가 이 모듈을 문다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from report_gen.source_roots import normalize_root_key, split_source_roots

__all__ = [
    "MapUse",
    "ProjectMaps",
    "resolve_project_maps",
    "describe_for_report",
    "needs_attention",
    "list_projects",
    "map_counts",
    "write_project_map",
    "update_project_roots",
    "read_manifest",
    "roots_cover",
    "roots_key",
    "root_keys",
    "PROJECT_MAPS_DIR",
    "MANIFEST_NAME",
    "MAP_KINDS",
    "MAP_FILE_NAMES",
    "STATUSES",
    "WARN_STATUSES",
]

_logger = logging.getLogger(__name__)

#: 저장소 루트의 `docs/project_maps` — CWD 와 무관하게 이 파일 위치에서 정한다(옛 설정 엔드포인트의 `"docs/…"` 는 CWD 상대였다).
PROJECT_MAPS_DIR = Path(__file__).resolve().parent.parent / "docs" / "project_maps"
MANIFEST_NAME = "project.json"
MANIFEST_SCHEMA = 1
MAP_KINDS: Tuple[str, ...] = ("component_map", "override")
MAP_FILE_NAMES: Dict[str, str] = {
    "component_map": "component_map.json",
    "override": "uds_function_swcom_override.json",
}
_MAP_TYPES: Dict[str, type] = {"component_map": list, "override": dict}
_KIND_KO: Dict[str, str] = {"component_map": "component_map(파일 → SwCom · 시험 범위)",
                            "override": "override(함수 → SwCom · Related · ASIL)"}

STATUS_APPLIED = "applied"
STATUS_NONE = "none"
STATUS_NOT_THIS_PROJECT = "not_this_project"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_INVALID = "invalid"
STATUS_NO_ROOTS = "no_roots"
STATUSES: Tuple[str, ...] = (STATUS_APPLIED, STATUS_NONE, STATUS_NOT_THIS_PROJECT, STATUS_AMBIGUOUS,
                             STATUS_INVALID, STATUS_NO_ROOTS)
#: 사람이 보고 고쳐야 맵이 걸리는 판정 — 공시는 warning, UDS 는 생성 항목. **단일 출처**(R97 리뷰 I8: `backend.helpers.uds` 와
#:   `generation_disclosures` 가 같은 튜플을 따로 들고 있었다 — 한쪽만 고치면 화면과 항목이 다른 말을 한다).
#:   `none`(이 프로젝트가 그 맵을 등록하지 않음) · `no_roots` 는 정보다.
WARN_STATUSES: Tuple[str, ...] = (STATUS_NOT_THIS_PROJECT, STATUS_AMBIGUOUS, STATUS_INVALID)
#: 매니페스트 맵 항목에서 판정에 쓰는 키 — 나머지(`table_files_not_in_source` 등)는 공시용 세부(`MapUse.details`)로 싣는다
_SPEC_CORE_KEYS = ("file", "origin", "generated_at")

#: 프로젝트 폴더 이름(키) — 레지스트리 id(`hdpdm01` · `kjpds02_pv`) 또는 `roots-<sha1>`. 경로 구분자 · `..` 는 못 들어온다.
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

_WRITE_LOCK = threading.Lock()


@dataclass(frozen=True)
class MapUse:
    """한 종류(`component_map` / `override`)의 맵을 이 생성에 쓰는가.

    `data` 는 `applied` 일 때만 채운다(목록 또는 dict — **소비자는 고치지 말 것**: 같은 해석이 캐시 키를 정한다).
    """

    kind: str
    status: str
    project: str = ""
    data: Any = field(default=None, compare=False, hash=False, repr=False)
    file: str = ""
    sha1: str = ""
    reason: str = ""
    others: Tuple[str, ...] = ()
    scm_id: str = ""
    origin: str = ""
    #: (R97 리뷰 W3) 읽지 못한 매니페스트 — 있으면 `applied` 라도 사람이 볼 일이다(그 매니페스트가 같은 루트를 주장했을 수 있다)
    problems: Tuple[str, ...] = ()
    #: 매니페스트가 맵 옆에 적은 세부(예: 구조 표에는 있는데 소스에 없는 파일 — 문서 결함 후보). 공시가 이름으로 말한다.
    details: Dict[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)

    @property
    def applied(self) -> bool:
        return self.status == STATUS_APPLIED

    def describe(self) -> Dict[str, Any]:
        """JSON 으로 그대로 실을 수 있는 기술(데이터 본문은 빼고 개수만)."""
        entries: Optional[int] = None
        if isinstance(self.data, (list, dict)):
            entries = len(self.data)
        return {
            "kind": self.kind,
            "status": self.status,
            "project": self.project,
            "scm_id": self.scm_id,
            "file": self.file,
            "sha1": self.sha1,
            "entries": entries,
            "origin": self.origin,
            "reason": self.reason,
            "others": list(self.others),
            "problems": list(self.problems),
            "details": json.loads(json.dumps(self.details, ensure_ascii=False, default=str)) if self.details else {},
        }


def needs_attention(desc: Any) -> bool:
    """기술(`MapUse.describe()`) 하나가 사람이 볼 일인가 — 경고 판정(`WARN_STATUSES`) 또는 읽지 못한 매니페스트. 공시 · UDS 항목의 단일 판정."""
    if not isinstance(desc, dict):
        return False
    return str(desc.get("status") or "") in WARN_STATUSES or bool(desc.get("problems"))


@dataclass(frozen=True)
class ProjectMaps:
    component_map: MapUse
    override: MapUse
    fingerprint: str

    def describe(self) -> Dict[str, Dict[str, Any]]:
        return {"component_map": self.component_map.describe(), "override": self.override.describe()}


@dataclass(frozen=True)
class _Manifest:
    key: str
    directory: Path
    scm_id: str
    project: str
    roots: frozenset
    maps: Dict[str, Dict[str, str]] = field(compare=False, hash=False)


def root_keys(source_root: Any) -> List[str]:
    """`"D:/a, d:\\b"` → 정규화 키 목록(빈 조각 제거, 순서 유지, 중복 제거)."""
    out: List[str] = []
    for piece in split_source_roots(source_root):
        k = normalize_root_key(piece)
        if k and k not in out:
            out.append(k)
    return out


def roots_key(source_root: Any) -> str:
    """레지스트리 항목이 없는 루트 묶음의 프로젝트 폴더 이름 — `roots-<sha1 12자>`(정규화 키를 정렬해 잇는다)."""
    keys = sorted(root_keys(source_root))
    return "roots-" + hashlib.sha1("\n".join(keys).encode("utf-8")).hexdigest()[:12]


def _manifest_roots(raw: Any) -> frozenset:
    items: Iterable[Any] = raw if isinstance(raw, (list, tuple)) else [raw]
    keys = set()
    for item in items:
        for piece in split_source_roots(item):
            k = normalize_root_key(piece)
            if k:
                keys.add(k)
    return frozenset(keys)


def _load_manifests(base: Path) -> Tuple[List[_Manifest], List[str]]:
    """`base/<key>/project.json` 전부. 못 읽은 것은 버리지 않고 **사유 목록**으로 돌려준다(공시가 말한다)."""
    manifests: List[_Manifest] = []
    problems: List[str] = []
    try:
        if not base.is_dir():
            return manifests, problems
        dirs = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError as exc:
        _logger.warning("프로젝트 맵 폴더를 읽지 못했다 %s: %s", base, exc)
        return manifests, [f"{base.name}: 폴더를 읽지 못함({type(exc).__name__})"]
    for d in dirs:
        mf = d / MANIFEST_NAME
        if not mf.is_file():
            # (R97 리뷰2 I-a) 맵 파일이 든 폴더만 문제다 — 매니페스트를 잃은 프로젝트일 수 있다. **빈 폴더**(중단된 쓰기 · 손으로 만든
            #   자리)까지 문제로 세면 그 폴더 하나가 모든 프로젝트의 맵을 경고로, PV override 를 `invalid` 로 바꾼다.
            if any((d / name).is_file() for name in MAP_FILE_NAMES.values()):
                problems.append(f"{d.name}: {MANIFEST_NAME} 없음 — 이 폴더의 맵은 어느 프로젝트에도 쓰지 않는다")
            else:
                _logger.debug("프로젝트 맵 폴더 %s 에 매니페스트도 맵도 없다 — 건너뛴다", d)
            continue
        try:
            raw = json.loads(mf.read_bytes().decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            _logger.warning("프로젝트 맵 매니페스트를 읽지 못했다 %s: %s", mf, exc)
            problems.append(f"{d.name}: 매니페스트를 읽지 못함({type(exc).__name__})")
            continue
        if not isinstance(raw, dict) or raw.get("schema") != MANIFEST_SCHEMA:
            problems.append(f"{d.name}: 매니페스트 형식이 아니다(schema {MANIFEST_SCHEMA} 인 객체여야 한다)")
            continue
        maps: Dict[str, Dict[str, str]] = {}
        raw_maps = raw.get("maps") if isinstance(raw.get("maps"), dict) else {}
        for kind in MAP_KINDS:
            spec = raw_maps.get(kind)
            if isinstance(spec, str):
                spec = {"file": spec}
            if isinstance(spec, dict) and str(spec.get("file") or "").strip():
                maps[kind] = {"file": str(spec.get("file")).strip(), "origin": str(spec.get("origin") or ""),
                              "details": {k: v for k, v in spec.items() if k not in _SPEC_CORE_KEYS}}
        scm_id = str(raw.get("scm_id") or "").strip()
        manifests.append(_Manifest(
            key=d.name,
            directory=d,
            scm_id=scm_id,
            project=str(raw.get("project") or "").strip() or scm_id or d.name,
            roots=_manifest_roots(raw.get("source_roots")),
            maps=maps,
        ))
    return manifests, problems


def _read_map(m: _Manifest, kind: str) -> MapUse:
    spec = m.maps[kind]
    fname = spec["file"]
    rel = f"{m.key}/{fname}"
    path = m.directory / fname
    try:
        inside = path.resolve().is_relative_to(m.directory.resolve())
    except (OSError, ValueError):
        inside = False
    if not inside:
        return MapUse(kind, STATUS_INVALID, project=m.project, file=rel, scm_id=m.scm_id, origin=spec["origin"],
                      reason="맵 파일 경로가 프로젝트 폴더 밖을 가리킨다 — 쓰지 않는다")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _logger.warning("프로젝트 맵을 읽지 못했다 %s: %s", path, exc)
        return MapUse(kind, STATUS_INVALID, project=m.project, file=rel, scm_id=m.scm_id, origin=spec["origin"],
                      reason=f"맵 파일을 읽지 못했다({type(exc).__name__}) — 쓰지 않는다")
    sha1 = hashlib.sha1(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        _logger.warning("프로젝트 맵이 JSON 이 아니다 %s: %s", path, exc)
        return MapUse(kind, STATUS_INVALID, project=m.project, file=rel, sha1=sha1, scm_id=m.scm_id,
                      origin=spec["origin"], reason=f"맵 파일이 JSON 이 아니다({type(exc).__name__}) — 쓰지 않는다")
    want = _MAP_TYPES[kind]
    if not isinstance(data, want):
        return MapUse(kind, STATUS_INVALID, project=m.project, file=rel, sha1=sha1, scm_id=m.scm_id,
                      origin=spec["origin"],
                      reason=f"맵 형식이 {'목록' if want is list else '객체'} 이 아니다({type(data).__name__}) — 쓰지 않는다")
    return MapUse(kind, STATUS_APPLIED, project=m.project, data=data, file=rel, sha1=sha1, scm_id=m.scm_id,
                  origin=spec["origin"], details=dict(spec.get("details") or {}),
                  reason=f"프로젝트 {m.project} 의 맵")


def _use_for(kind: str, matched: Optional[List[_Manifest]], manifests: List[_Manifest], how: str,
             problems: List[str]) -> MapUse:
    """(R97 리뷰 W3) 읽지 못한 매니페스트가 있으면 '맵 없음(none)' · '남의 맵(not_this_project)' 을 **말할 수 없다** — 그
    매니페스트가 이 루트의 프로젝트였을 수 있다(실측: HD `project.json` 끝 5바이트가 잘리면 HD 루트의 override 가 `none`(정보)이
    되어 ASIL override 가 조용히 사라졌다). 그 둘은 `invalid`(경고)로 바꾸고, 다른 판정에도 `problems` 를 붙여 공시가 경고로 말한다."""
    use = _use_for_inner(kind, matched, manifests, how, problems)
    if not problems:
        return use
    probs = tuple(problems)
    if use.status in (STATUS_NONE, STATUS_NOT_THIS_PROJECT):
        return replace(use, status=STATUS_INVALID, data=None, problems=probs,
                       reason=("읽지 못한 매니페스트가 있어 이 루트의 맵이 없는지 판정할 수 없다 — 맵을 쓰지 않는다("
                               + "; ".join(probs[:3]) + (" …" if len(probs) > 3 else "") + "). 판정 전: " + use.reason))
    return replace(use, problems=probs)


def _use_for_inner(kind: str, matched: Optional[List[_Manifest]], manifests: List[_Manifest], how: str,
                   problems: List[str]) -> MapUse:
    tail = (" · 읽지 못한 매니페스트: " + "; ".join(problems[:3]) + (" …" if len(problems) > 3 else "")) if problems else ""
    if matched is None:
        return MapUse(kind, STATUS_NO_ROOTS,
                      reason="소스 루트도 SCM id 도 없어 프로젝트를 정할 수 없다 — 맵을 쓰지 않는다" + tail)
    if len(matched) > 1:
        names = tuple(sorted(m.key for m in matched))
        return MapUse(kind, STATUS_AMBIGUOUS, others=names,
                      reason=f"{how} 이(가) 프로젝트 {len(matched)}개({', '.join(names)})에 맞는다 — 고르지 않고 맵을 쓰지 않는다"
                             + tail)
    if len(matched) == 1:
        m = matched[0]
        if kind not in m.maps:
            return MapUse(kind, STATUS_NONE, project=m.project, scm_id=m.scm_id,
                          reason=f"프로젝트 {m.project} 는 {_KIND_KO[kind]} 맵을 등록하지 않았다" + tail)
        return _read_map(m, kind)
    holders = tuple(sorted(m.key for m in manifests if kind in m.maps))
    if holders:
        return MapUse(kind, STATUS_NOT_THIS_PROJECT, others=holders,
                      reason=(f"{how} 에 맞는 프로젝트 맵이 없다 — 등록된 {_KIND_KO[kind]} 맵은 다른 프로젝트"
                              f"({', '.join(holders)}) 것이라 쓰지 않는다") + tail)
    return MapUse(kind, STATUS_NONE, reason=f"등록된 {_KIND_KO[kind]} 맵이 없다" + tail)


def resolve_project_maps(source_root: Any, *, scm_id: Optional[str] = None,
                         base_dir: Optional[Path] = None) -> ProjectMaps:
    """이 생성(소스 루트 · SCM id)에 쓸 프로젝트 맵을 정한다 — 판정 규칙은 모듈 docstring.

    Args:
        source_root: 생성 소스 루트(콤마 · 세미콜론 복수 허용).
        scm_id: 등록 항목 id 를 아는 호출자가 준다. 주면 루트보다 먼저다.
        base_dir: 테스트용 — 없으면 `PROJECT_MAPS_DIR`(호출 시점에 읽는다).

    Returns:
        `ProjectMaps` — 종류마다 `MapUse` 와 캐시 지문.
    """
    base = Path(base_dir) if base_dir is not None else PROJECT_MAPS_DIR
    manifests, problems = _load_manifests(base)
    sid = str(scm_id or "").strip()
    roots = root_keys(source_root)
    rset = set(roots)
    by_roots = [m for m in manifests if m.roots and rset <= m.roots] if roots else None
    roots_how = "소스 루트(" + ", ".join(split_source_roots(source_root)[:3]) + ")"
    matched: Optional[List[_Manifest]]
    if sid:
        matched = [m for m in manifests if m.scm_id and m.scm_id.lower() == sid.lower()]
        how = f"SCM id `{sid}`"
        if len(matched) == 1 and roots and not rset <= matched[0].roots:
            return _roots_moved(matched[0], by_roots or [], manifests, roots_how, problems, source_root)
    elif roots:
        matched = by_roots
        how = roots_how
    else:
        matched = None
        how = ""
    cm = _use_for("component_map", matched, manifests, how, problems)
    ov = _use_for("override", matched, manifests, how, problems)
    return _maps(cm, ov)


def _maps(cm: MapUse, ov: MapUse) -> ProjectMaps:
    fingerprint = "|".join(f"{u.kind}={u.status}:{u.project}:{u.sha1}" for u in (cm, ov))
    return ProjectMaps(component_map=cm, override=ov, fingerprint=fingerprint)


def _roots_moved(m: _Manifest, by_roots: List[_Manifest], manifests: List[_Manifest], roots_how: str,
                 problems: List[str], source_root: Any) -> ProjectMaps:
    """(R97 리뷰2 W1) id 로 고른 매니페스트의 루트가 이 생성 루트를 담지 못한다 — 레지스트리 루트만 바뀌고 매니페스트는 옛 루트다.

    id 경로(준비 게이트 · 측정 · 영향 분석 재생성)가 여기서 맵을 쓰면, 같은 입력을 루트로 고르는 문서 생성 허브는
    `not_this_project` 라 두 경로의 문서가 SwUFn · ASIL 에서 갈렸다(게이트가 잰 문서 ≠ 만든 문서). 그래서 **루트 경로와 똑같이**
    판정하고(같은 상태 · 같은 지문 → 같은 캐시), 루트 경로가 다른 프로젝트 맵을 쓸 수 있는 경우에도 id 가 그 프로젝트가 아니라고
    말하므로 쓰지 않는다(fail-closed). 사유에 '루트가 옮겨졌다 — 관리자가 루트를 다시 등록할 것' 을 싣는다.
    """
    note = (f"roots_moved: SCM id `{m.scm_id}` 의 매니페스트({m.key}) 루트가 이 생성 루트("
            + ", ".join(split_source_roots(source_root)[:3]) + ")를 담지 않는다")
    guide = (" — 레지스트리 루트만 바뀐 것이면 맵을 다시 만들지 말고 관리자가 프로젝트 설정에서 루트를 다시 등록할 것"
             "(`/api/local/project-setup/update-roots`)")
    uses = []
    for kind in MAP_KINDS:
        use = _use_for(kind, by_roots, manifests, roots_how, problems)
        if use.applied:
            # 루트로는 다른 프로젝트 맵이 맞지만 id 는 그 프로젝트가 아니라고 한다 — 둘 중 하나를 고르지 않는다
            use = replace(use, status=STATUS_NOT_THIS_PROJECT, data=None, others=(m.key,),
                          reason=f"SCM id `{m.scm_id}` 와 루트가 가리키는 프로젝트({use.project})가 다르다 — 맵을 쓰지 않는다")
        uses.append(replace(use, problems=tuple(use.problems) + (note,), reason=use.reason + ". " + note + guide))
    return _maps(*uses)


def describe_for_report(pmaps: ProjectMaps, stage: Any = None) -> Dict[str, Dict[str, Any]]:
    """품질 리포트용 기술 — 생성기가 고른 맵(`pmaps`)에 소스 단계 payload 의 `project_maps`(`stage`)를 대조해 붙인다.

    소스 단계 결과는 캐시에서 올 수 있고 캐시 키는 맵 지문을 담지만, 생성기가 맵을 고른 뒤 캐시를 읽는 사이 맵 파일이 바뀌면
    두 판정이 갈린다(SwCom 라벨은 옛 맵, 보충 · 시험 범위는 새 맵). 드문 경합이지만 갈렸으면 `source_stage` 로 말한다 — 조용히
    한쪽을 믿지 않는다. 소스 단계가 업로드 목록(`used=argument`)을 썼으면 그것도 옮겨 적는다.
    """
    out = pmaps.describe()
    st = stage if isinstance(stage, dict) else {}
    for kind, d in out.items():
        sd = st.get(kind) if isinstance(st.get(kind), dict) else None
        if sd is None:
            d["source_stage"] = "unrecorded" if st else "absent"
            continue
        if sd.get("used") == "argument":
            d["source_stage"] = "argument"
            d["argument_entries"] = sd.get("argument_entries")
        elif (sd.get("status"), sd.get("project"), sd.get("sha1")) != (d["status"], d["project"], d["sha1"]):
            d["source_stage"] = "differs"
            d["source_stage_status"] = sd.get("status")
            d["source_stage_project"] = sd.get("project")
        else:
            d["source_stage"] = "same"
    return out


def map_counts(kind: str, data: Any) -> Dict[str, Any]:
    if kind == "component_map" and isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
        return {
            "entries": len(rows),
            "verify_o": sum(1 for r in rows if str(r.get("verify") or "").strip().upper() == "O"),
            "verify_x": sum(1 for r in rows if str(r.get("verify") or "").strip().upper() == "X"),
        }
    if kind == "override" and isinstance(data, dict):
        vals = [v for v in data.values() if isinstance(v, dict)]
        return {
            "functions": len(data),
            "with_asil": sum(1 for v in vals if v.get("asil")),
            "swcom_count": len({v.get("swcom") for v in vals}),
        }
    return {}


def roots_cover(manifest_roots: Any, source_root: Any) -> bool:
    """매니페스트 루트가 이 생성 루트를 모두 담는가(R ⊆ M) — 판정(`resolve_project_maps`)과 같은 정규화. 빈 R 은 True 가 아니다."""
    r = set(root_keys(source_root))
    return bool(r) and r <= _manifest_roots(manifest_roots)


def read_manifest(key: str, base_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """프로젝트 폴더의 매니페스트 원문(dict) — 없으면 None. 못 읽으면 `ValueError`(사람이 적은 출처를 덮지 않게 호출자가 멈춘다)."""
    if not _KEY_RE.match(str(key or "")) or key in (".", ".."):
        raise ValueError(f"invalid project key: {key!r}")
    mf = (Path(base_dir) if base_dir is not None else PROJECT_MAPS_DIR) / key / MANIFEST_NAME
    if not mf.is_file():
        return None
    try:
        loaded = json.loads(mf.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"existing manifest unreadable: {type(exc).__name__}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("existing manifest is not an object")
    return loaded


def list_projects(base_dir: Optional[Path] = None, source_root: Any = "") -> Dict[str, Any]:
    """설정 화면용 — 등록된 프로젝트와 맵별 상태 · 개수. `{"projects": [...], "problems": [...]}`.

    `source_root` 를 주면 프로젝트마다 `roots_covered`(그 루트가 매니페스트 루트에 드는가)를 싣는다 — (R97 리뷰 W7) 레지스트리 루트가
    바뀌어 맵이 안 걸릴 때, 화면이 "맵을 다시 만들라" 가 아니라 "루트를 다시 등록하라" 를 말할 근거다.
    """
    base = Path(base_dir) if base_dir is not None else PROJECT_MAPS_DIR
    manifests, problems = _load_manifests(base)
    projects: List[Dict[str, Any]] = []
    for m in manifests:
        maps: Dict[str, Any] = {}
        for kind in MAP_KINDS:
            if kind not in m.maps:
                continue
            use = _read_map(m, kind)
            maps[kind] = {**use.describe(), **map_counts(kind, use.data)}
        row: Dict[str, Any] = {
            "key": m.key,
            "scm_id": m.scm_id,
            "project": m.project,
            "source_roots": sorted(m.roots),
            "maps": maps,
        }
        if root_keys(source_root):
            row["roots_covered"] = set(root_keys(source_root)) <= m.roots
        projects.append(row)
    return {"projects": projects, "problems": problems}


def _dump_json(path: Path, payload: Any) -> None:
    """UTF-8 · LF 로 원자적으로 쓴다 — 옛 설정 엔드포인트는 `open(out, "w")` 라 Windows 로케일(cp949)로 썼고 읽는 쪽은 utf-8 이었다."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def write_project_map(kind: str, data: Any, *, key: str, project: str, scm_id: str = "",
                      source_roots: Iterable[str] = (), origin: str = "", overwrite: bool = False,
                      replace_roots: bool = False, details: Optional[Dict[str, Any]] = None,
                      base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """프로젝트 폴더에 맵을 쓰고 매니페스트에 등록한다.

    같은 프로젝트에 같은 종류의 맵이 이미 있으면 `overwrite` 없이는 `FileExistsError` — 사람이 정한 맵(HDPDM01 verify=X 49행)을
    자동 생성물이 조용히 덮지 않게. 덮을 때는 옛 파일을 `<이름>.prev` 로 남긴다.

    `replace_roots`: 매니페스트 루트를 `source_roots` 로 **바꾼다**(기본은 비어 있을 때만 채움). 호출자(설정 엔드포인트)가 레지스트리
    항목 id 가 매니페스트 id 와 같을 때만 켠다 — 레지스트리 루트가 바뀐 프로젝트의 맵이 다시 걸리게(R97 리뷰 W7).
    `details`: 맵 옆에 적을 세부(구조 표의 문서 결함 후보 · 동명 파일 처리 등) — 판정에는 안 쓰고 공시가 이름으로 말한다.

    Raises:
        ValueError: 모르는 종류 · 키 형식 · 데이터 형식 · 못 읽는 기존 매니페스트.
        FileExistsError: 같은 맵이 있고 `overwrite=False`.
    """
    if kind not in MAP_KINDS:
        raise ValueError(f"unknown map kind: {kind}")
    if not _KEY_RE.match(str(key or "")) or key in (".", ".."):
        raise ValueError(f"invalid project key: {key!r}")
    if not isinstance(data, _MAP_TYPES[kind]):
        raise ValueError(f"{kind} data must be {_MAP_TYPES[kind].__name__}")
    base = Path(base_dir) if base_dir is not None else PROJECT_MAPS_DIR
    d = base / key
    target = d / MAP_FILE_NAMES[kind]
    mf = d / MANIFEST_NAME
    roots_list = [str(r) for r in source_roots if str(r).strip()]
    with _WRITE_LOCK:
        # 매니페스트를 먼저 읽는다 — 못 읽으면 맵 파일도 건드리지 않는다(반쯤 쓴 상태를 남기지 않게)
        manifest = read_manifest(key, base) or {}
        d.mkdir(parents=True, exist_ok=True)
        backup = ""
        if target.exists():
            if not overwrite:
                raise FileExistsError(str(target))
            prev = target.with_name(target.name + ".prev")
            shutil.copy2(target, prev)
            backup = str(prev)
        before_roots = list(manifest.get("source_roots") or [])
        manifest["schema"] = MANIFEST_SCHEMA
        manifest.setdefault("scm_id", str(scm_id or ""))
        manifest.setdefault("project", str(project or scm_id or key))
        if replace_roots and roots_list:
            manifest["source_roots"] = roots_list
        elif not manifest.get("source_roots"):
            manifest["source_roots"] = roots_list
        maps = manifest.get("maps") if isinstance(manifest.get("maps"), dict) else {}
        entry: Dict[str, Any] = {"file": MAP_FILE_NAMES[kind], "origin": str(origin or ""),
                                 "generated_at": datetime.now().isoformat(timespec="seconds")}
        for k, v in (details or {}).items():
            if k not in _SPEC_CORE_KEYS:
                entry[k] = v
        maps[kind] = entry
        manifest["maps"] = maps
        _dump_json(target, data)
        _dump_json(mf, manifest)
    covered = (set(root_keys(",".join(roots_list))) <= _manifest_roots(manifest.get("source_roots"))) if roots_list \
        else True
    return {"key": key, "path": str(target), "manifest": str(mf), "backup": backup,
            "manifest_roots": list(manifest.get("source_roots") or []),
            "roots_before": before_roots,
            # 매니페스트가 이미 있던 프로젝트면 루트는 그쪽 것이 남는다(replace_roots 아니면) — 준 루트가 거기 안 들면 루트 판정으로는
            #   이 맵이 안 걸린다
            "roots_covered": bool(covered)}


def update_project_roots(key: str, source_roots: Iterable[str], *, scm_id: str,
                         base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """(R97 리뷰 W7) 맵은 그대로 두고 **매니페스트 루트만** 다시 등록한다 — 레지스트리 루트가 바뀌어 맵이 안 걸리는 프로젝트용.

    맵을 다시 만들면 사람이 정한 맵(HDPDM01 verify=X 49행)이 자동 생성물(전부 O)로 바뀐다. 루트가 바뀐 것이면 그게 답이 아니다.
    매니페스트의 `scm_id` 가 주어진 id 와 같을 때만(대소문자 무시) 고친다 — 남의 프로젝트 루트를 옮기지 않게.

    Raises:
        FileNotFoundError: 그 프로젝트에 매니페스트가 없다.
        ValueError: id 불일치 · 빈 루트 · 못 읽는 매니페스트 · 키 형식.
    """
    roots_list = [str(r) for r in source_roots if str(r).strip()]
    if not roots_list:
        raise ValueError("source_roots is empty")
    base = Path(base_dir) if base_dir is not None else PROJECT_MAPS_DIR
    with _WRITE_LOCK:
        manifest = read_manifest(key, base)
        if manifest is None:
            raise FileNotFoundError(str(base / key / MANIFEST_NAME))
        have = str(manifest.get("scm_id") or "").strip()
        if not have or have.lower() != str(scm_id or "").strip().lower():
            raise ValueError(f"manifest scm_id {have!r} does not match {scm_id!r}")
        before = list(manifest.get("source_roots") or [])
        manifest["source_roots"] = roots_list
        manifest["roots_updated_at"] = datetime.now().isoformat(timespec="seconds")
        _dump_json(base / key / MANIFEST_NAME, manifest)
    return {"key": key, "roots_before": before, "roots_after": roots_list}
