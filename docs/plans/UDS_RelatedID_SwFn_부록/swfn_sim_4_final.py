# -*- coding: utf-8 -*-
"""병기 시뮬레이션 4/4 — ASIL 불변 확인 · 미도달 요구 정체 · 최대 fan-out 요구."""
import collections
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path.cwd()))
from backend.services.file_resolver import CloudiumFileResolver  # noqa: E402
from report_gen.requirements import (  # noqa: E402
    _docx_to_text,
    _extract_sds_partition_map,
    _safe_docx_open,
    build_sds_component_maps,
    generate_uds_requirements_preview,
    generate_uds_traceability_matrix,
)

BASE = ("U:/연구소/1000 프로젝트/1200 자동차/1220 진행/0002 A Cappella/02 ADOS/04 KJPDS02/"
        "02.설계(연구소)/01.설계 및 검증/08.소프트웨어/")
SRS = BASE + "01.SW 요구사항/01.SwRS/(KJPDS02_SwRS) Software Requirements Specification_v3.01_20260410_R.docx"
SDS = BASE + "03.SW 아키텍처 설계/01.SwDS/(KJPDS02_SwDS) Software Architecture Design Specification_v3.01_20260410_R.docx"
SP = pathlib.Path(sys.argv[1])
base = json.loads((SP / "baseline.json").read_text(encoding="utf-8"))
eff = json.loads((SP / "effect.json").read_text(encoding="utf-8"))
uds_rows = base["uds_rows"]


def read(p):
    return CloudiumFileResolver(allowed_prefixes=p.rsplit("/", 1)[0]).read_bytes(p)


def tmpdoc(p):
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
        tf.write(read(p))
        return tf.name


t = tmpdoc(SRS)
req_items = [i for i in generate_uds_requirements_preview([_docx_to_text(_safe_docx_open(t))])["items"]
             if str(i.get("id") or "").strip()]
pathlib.Path(t).unlink(missing_ok=True)
t = tmpdoc(SDS)
pm = _extract_sds_partition_map(t)
pathlib.Path(t).unlink(missing_ok=True)
m = build_sds_component_maps(pm)
sds_pairs = [{"requirement_id": rid, "component_ids": c,
              "design_component_ids": m["req_to_design_comps"].get(rid, []),
              "folded_component_ids": m["req_to_folded_comps"].get(rid, []),
              "design_element_ids": m["req_to_element_comps"].get(rid, [])}
             for rid, c in sorted(m["req_to_comps"].items())]
uds_func_ids = sorted({r["unit"] for r in uds_rows if r["unit"]})


def mp(assign=None):
    pairs = collections.defaultdict(list)
    for r in uds_rows:
        disp = [x for x in (r["unit"], r["uid"]) if x]
        toks = list(r["req_direct"]) + list(r["design_ids"]) + list(r["swcoms"])
        if assign and r["swcoms"] and not r["design_ids"] and not r["req_direct"]:
            for c in r["swcoms"]:
                toks += assign.get(c, [])
        for tk in set(toks):
            for d in disp:
                if d not in pairs[tk]:
                    pairs[tk].append(d)
    return [{"requirement_id": k, "source_ids": v} for k, v in pairs.items()]


def run(assign):
    return generate_uds_traceability_matrix(
        req_items, mapping_pairs=mp(assign), vcast_rows=[], sds_pairs=sds_pairs,
        sits_rows=[], uds_function_ids=uds_func_ids, component_asil=m["component_asil"])


m0, m1 = run(None), run(eff["opt_map"])
r0 = {r["requirement_id"]: r for r in m0["rows"]}
r1 = {r["requirement_id"]: r for r in m1["rows"]}

print("=" * 68)
print("A. ASIL — 병기가 안전등급을 건드리나")
print("=" * 68)
a0 = {k: v.get("asil") for k, v in r0.items()}
a1 = {k: v.get("asil") for k, v in r1.items()}
print(f"  행 ASIL 완전 일치: {a0 == a1}")
print(f"  ASIL 분포: {dict(collections.Counter(v or '(공백)' for v in a0.values()))}")
print("  ⟹ 행 ASIL 은 SDS component_ids 롤업 기준이라 UDS Related ID 와 무관하다.")

print("\n" + "=" * 68)
print("B. 커버리지 — 병기가 covered 를 늘리나")
print("=" * 68)
for lbl, rr in (("현재", r0), ("병기후", r1)):
    hd = sum(1 for v in rr.values() if v.get("sds_components") or v.get("sds_functions")
             or v.get("sds_design_elements") or v.get("source_ids") or v.get("hsis_signals"))
    uds = sum(1 for v in rr.values() if v.get("source_ids"))
    print(f"  {lbl:6} 설계보유 {hd}/{len(rr)} · UDS링크보유 {uds}/{len(rr)}")

print("\n" + "=" * 68)
print("C. UDS 링크 없는 요구의 정체")
print("=" * 68)
no_uds = sorted(k for k, v in r1.items() if not v.get("source_ids"))
print(f"  병기 후에도 UDS 링크 없음 = {len(no_uds)}건: {no_uds}")
for k in no_uds:
    v = r1[k]
    print(f"    {k:14} sds_comp={len(v.get('sds_components') or [])} "
          f"sds_fn={len(v.get('sds_functions') or [])} "
          f"elem={len(v.get('sds_design_elements') or [])} asil={v.get('asil') or '-'}")

print("\n" + "=" * 68)
print("D. fan-out 최악 요구 — 어디에 몰리나")
print("=" * 68)
top0 = sorted(r0.items(), key=lambda kv: -len(kv[1].get("source_ids") or []))[:5]
top1 = sorted(r1.items(), key=lambda kv: -len(kv[1].get("source_ids") or []))[:5]
print("  현재 상위:", [(k, len(v.get("source_ids") or [])) for k, v in top0])
print("  병기 상위:", [(k, len(v.get("source_ids") or [])) for k, v in top1])
worst = top1[0][0]
print(f"\n  최악 {worst}: {len(r0[worst].get('source_ids') or [])} → {len(r1[worst].get('source_ids') or [])}")
