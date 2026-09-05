# -*- coding: utf-8 -*-
"""병기 시뮬레이션 1/3 — 현재 상태 실측.

병기의 **한계 효과**를 재려면 "지금 이미 추적되는 함수"를 먼저 알아야 한다.
UDS 함수는 세 경로로 요구에 닿는다:

  ① 직접   UDS Related ID 에 요구ID(SwTR_ 등)가 적힘
  ② 이름   함수명이 SDS 함수 엔트리와 일치 → 그 엔트리의 Related ID (`sds_func_to_reqs`)
  ③ 설계ID UDS Related ID 의 SwFn_/SwSTR_/SwST_/SwTK_ → SDS 설계ID 엔트리의 Related ID

병기가 여는 건 ③ 뿐이다. ②가 이미 덮고 있는 함수엔 순증이 없다.
"""
import collections
import io
import json
import pathlib
import re
import sys
import tempfile
import zipfile

sys.path.insert(0, str(pathlib.Path.cwd()))
from backend.services.file_resolver import CloudiumFileResolver  # noqa: E402
from report_gen.requirements import (  # noqa: E402
    _extract_sds_partition_map,
    _normalize_req_id,
    _sds_comp_key,
)

BASE = ("U:/연구소/1000 프로젝트/1200 자동차/1220 진행/0002 A Cappella/02 ADOS/04 KJPDS02/"
        "02.설계(연구소)/01.설계 및 검증/08.소프트웨어/")
UDS = BASE + "04.SW 단위 설계/01.SwUDS/(KJPDS02_SwUDS) Software Unit Design Specification_v3.02_260XXX.docx"
SDS = BASE + "03.SW 아키텍처 설계/01.SwDS/(KJPDS02_SwDS) Software Architecture Design Specification_v3.01_20260410_R.docx"
OUT = pathlib.Path(sys.argv[1])


def read(path):
    return CloudiumFileResolver(allowed_prefixes=path.rsplit("/", 1)[0]).read_bytes(path)


TBL = re.compile(r"<w:tbl[ >].*?</w:tbl>", re.S)
ROW = re.compile(r"<w:tr[ >].*?</w:tr>", re.S)
CELL = re.compile(r"<w:tc[ >].*?</w:tc>", re.S)
T = re.compile(r"<w:t[^>]*>(.*?)</w:t>", re.S)


def txt(frag):
    return " ".join(re.sub(r"<[^>]+>", "", "".join(T.findall(frag))).split()).strip()


# ── UDS: 함수별 (SwUFn ID, 함수명, Related ID) ──────────────────────────────
xml = zipfile.ZipFile(io.BytesIO(read(UDS))).read("word/document.xml").decode("utf-8", "ignore")
uds_rows = []
for tbl in TBL.finditer(xml):
    kv, order = {}, []
    for row in ROW.finditer(tbl.group(0)):
        cells = [txt(c.group(0)) for c in CELL.finditer(row.group(0))]
        if len(cells) < 2:
            continue
        lab = cells[0].lower()
        val = next((x for x in cells[1:] if x), "")
        if lab and lab not in kv:
            kv[lab] = val
            order.append(lab)
    rel_key = next((k for k in order if re.search(r"related", k)), "")
    if not rel_key:
        continue
    # proto 는 부록 A 에서 팀이 SwFn 을 판단할 단서로 쓴다 — UDS 파서를 여기 하나로 유지하려고
    # 소비처(swfn_assign_appendix.py)가 아니라 이 파일에서 함께 뽑는다.
    uds_rows.append({"uid": kv.get("id", ""), "unit": kv.get("name", ""),
                     "proto": kv.get("prototype", "")[:70],
                     "related": kv.get(rel_key, "")})
print(f"UDS 함수 표 {len(uds_rows)}")

DESIGN_BRIDGE = re.compile(r"^SW(?:FN|STR|ST|TK)_\d+$")
REQ_NS = re.compile(r"^SW(?:TR|TSR|NTR|NTSR|CNF|EI)_\d+$")
TOKEN = re.compile(r"Sw[A-Za-z]{2,}\s*_?\s*\d+", re.I)

for r in uds_rows:
    toks = [_normalize_req_id(t) for t in TOKEN.findall(r["related"])]
    r["req_direct"] = sorted({t for t in toks if REQ_NS.match(t)})
    r["design_ids"] = sorted({t for t in toks if DESIGN_BRIDGE.match(t)})
    r["swcoms"] = sorted({t for t in toks if t.startswith("SWCOM_")})

n_direct = sum(1 for r in uds_rows if r["req_direct"])
n_design = sum(1 for r in uds_rows if r["design_ids"])
n_swcom_only = sum(1 for r in uds_rows if r["swcoms"] and not r["design_ids"] and not r["req_direct"])
print(f"  ① 직접 요구ID 보유      : {n_direct}")
print(f"  ③ 설계ID 보유(브리지 가능): {n_design}")
print(f"  SwCom 단독(브리지 불가)  : {n_swcom_only}")

# ── SDS 파티션 맵 ───────────────────────────────────────────────────────────
with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
    tf.write(read(SDS))
    tmp = tf.name
pm = _extract_sds_partition_map(tmp)
pathlib.Path(tmp).unlink(missing_ok=True)
print(f"\nSDS 파티션 엔트리 {len(pm)}")
print("  kind 분포:", dict(collections.Counter(str((v or {}).get('kind') or '?') for v in pm.values())))

# SDS 함수 엔트리 이름 집합 (② 이름 브리지의 소스)
sds_fn_keys = {_sds_comp_key(k) for k, v in pm.items()
               if str((v or {}).get("kind") or "") == "function" and (v or {}).get("related")}
print(f"  related 보유 function 엔트리(이름 브리지 소스) = {len(sds_fn_keys)}")

# 설계ID 엔트리 → 요구
design_to_reqs = {}
swcom_to_reqs = {}
for k, v in pm.items():
    if not isinstance(v, dict) or not v.get("related"):
        continue
    key = _normalize_req_id(k)
    reqs = sorted({_normalize_req_id(t) for t in TOKEN.findall(str(v.get("related")))
                   if REQ_NS.match(_normalize_req_id(t))})
    if not reqs:
        continue
    if DESIGN_BRIDGE.match(key):
        design_to_reqs[key] = reqs
    elif key.startswith("SWCOM_"):
        swcom_to_reqs[key] = reqs
print(f"  설계ID 엔트리(요구 보유) = {len(design_to_reqs)}  "
      f"(SwFn {sum(1 for k in design_to_reqs if k.startswith('SWFN_'))})")
print(f"  SwCom 엔트리(요구 보유)  = {len(swcom_to_reqs)}")

# ── ② 이름 브리지가 지금 덮는 UDS 함수 ──────────────────────────────────────
covered_by_name = [r for r in uds_rows if _sds_comp_key(r["unit"]) in sds_fn_keys]
print(f"\n② 이름 브리지로 이미 SDS 함수와 이름이 맞는 UDS 함수 = {len(covered_by_name)} / {len(uds_rows)}")

swcom_only_rows = [r for r in uds_rows if r["swcoms"] and not r["design_ids"] and not r["req_direct"]]
swcom_only_named = [r for r in swcom_only_rows if _sds_comp_key(r["unit"]) in sds_fn_keys]
print(f"   그중 SwCom 단독 900행 안에서 이름이 맞는 것 = {len(swcom_only_named)} / {len(swcom_only_rows)}")
print(f"   ⟹ 병기의 **순증 후보** = {len(swcom_only_rows) - len(swcom_only_named)} 함수")

OUT.write_text(json.dumps({
    "uds_rows": uds_rows,
    "design_to_reqs": design_to_reqs,
    "swcom_to_reqs": swcom_to_reqs,
    "sds_fn_keys": sorted(sds_fn_keys),
}, ensure_ascii=False), encoding="utf-8")
print(f"\n저장: {OUT}")
