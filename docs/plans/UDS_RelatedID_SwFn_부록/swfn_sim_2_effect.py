# -*- coding: utf-8 -*-
"""병기 시뮬레이션 2/3 — 실제 파이프라인으로 전/후 매트릭스 생성·대조.

`mapping_pairs` 의 `requirement_id` 는 **UDS Related ID 의 토큰 그대로**다(요구ID일 수도
설계ID일 수도 있다). 설계ID면 `design_to_reqs` 를 타고 요구에 붙는다
(`requirements.py` 설계-ID bridge). 병기는 이 경로에 SwFn 을 새로 넣는 것이다.

배정(어느 함수가 어느 SwFn 인가)은 문서에 없으므로 **경계 두 개**로 잰다:
  낙관  SwCom 의 요구집합과 겹치는 SwFn 중 **가장 좁은 것 1개** (팀이 정확히 지정)
  비관  겹치는 SwFn **전부** (팀이 대충 나열)
"""
import collections
import json
import pathlib
import statistics
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path.cwd()))
from backend.services.file_resolver import CloudiumFileResolver  # noqa: E402
from report_gen.requirements import (  # noqa: E402
    _docx_to_text,
    _extract_sds_partition_map,
    _normalize_req_id,
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
uds_rows = base["uds_rows"]
design_to_reqs = base["design_to_reqs"]
swcom_to_reqs = base["swcom_to_reqs"]


def read(path):
    return CloudiumFileResolver(allowed_prefixes=path.rsplit("/", 1)[0]).read_bytes(path)


def tmpdoc(path, suffix=".docx"):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        tf.write(read(path))
        return tf.name


# ── SRS 요구 ────────────────────────────────────────────────────────────────
srs_tmp = tmpdoc(SRS)
preview = generate_uds_requirements_preview([_docx_to_text(_safe_docx_open(srs_tmp))])
pathlib.Path(srs_tmp).unlink(missing_ok=True)
req_items = [it for it in preview.get("items", []) if str(it.get("id") or "").strip()]
req_norm = {_normalize_req_id(str(it["id"])) for it in req_items}
print(f"SRS 요구 {len(req_items)}건 (distinct 정규화 {len(req_norm)})")
print(f"  예: {[it['id'] for it in req_items[:6]]}")

# ── SDS pairs (프로덕션 헬퍼) ───────────────────────────────────────────────
sds_tmp = tmpdoc(SDS)
pm = _extract_sds_partition_map(sds_tmp)
pathlib.Path(sds_tmp).unlink(missing_ok=True)
m = build_sds_component_maps(pm)
sds_pairs = [{"requirement_id": rid, "component_ids": comps,
              "design_component_ids": m["req_to_design_comps"].get(rid, []),
              "folded_component_ids": m["req_to_folded_comps"].get(rid, []),
              "design_element_ids": m["req_to_element_comps"].get(rid, [])}
             for rid, comps in sorted(m["req_to_comps"].items())]

# 설계ID 중 **매트릭스 요구에 실제로 닿는 것**만이 브리지에 유효하다
eff_design = {d: [r for r in rs if r in req_norm] for d, rs in design_to_reqs.items()}
eff_design = {d: rs for d, rs in eff_design.items() if rs}
eff_swcom = {c: [r for r in rs if r in req_norm] for c, rs in swcom_to_reqs.items()}
eff_swcom = {c: rs for c, rs in eff_swcom.items() if rs}
swfn_eff = {d: rs for d, rs in eff_design.items() if d.startswith("SWFN_")}
print(f"\n브리지 유효 설계ID = {len(eff_design)} (SwFn {len(swfn_eff)})")
print(f"브리지 유효 SwCom  = {len(eff_swcom)}")
print(f"SwFn 도달 요구 distinct = {len({r for rs in swfn_eff.values() for r in rs})}")
print(f"SwCom 도달 요구 distinct = {len({r for rs in eff_swcom.values() for r in rs})}")

# ── 병기 배정 (경계 2개) ────────────────────────────────────────────────────
opt_map, pes_map = {}, {}       # SwCom → [SwFn]
for com, creqs in eff_swcom.items():
    cset = set(creqs)
    cands = [(len(rs), d) for d, rs in swfn_eff.items() if cset & set(rs)]
    if not cands:
        continue
    cands.sort()
    opt_map[com] = [cands[0][1]]                 # 가장 좁은 1개
    pes_map[com] = [d for _, d in cands]         # 전부
print(f"\nSwCom→SwFn 후보: 배정 가능 SwCom {len(opt_map)}/{len(eff_swcom)}")
_c = [len(v) for v in pes_map.values()]
if _c:
    print(f"  후보 수 중앙 {statistics.median(_c):.0f} · 최대 {max(_c)}")


def build_mapping_pairs(assign=None):
    """UDS Related ID → mapping_pairs. assign 주면 SwCom 단독 행에 SwFn 을 **추가**."""
    pairs = collections.defaultdict(list)
    for r in uds_rows:
        disp = [x for x in (r["unit"], r["uid"]) if x]
        toks = list(r["req_direct"]) + list(r["design_ids"]) + list(r["swcoms"])
        if assign and r["swcoms"] and not r["design_ids"] and not r["req_direct"]:
            for com in r["swcoms"]:
                toks += assign.get(com, [])
        for t in set(toks):
            for d in disp:
                if d not in pairs[t]:
                    pairs[t].append(d)
    return [{"requirement_id": k, "source_ids": v} for k, v in pairs.items()]


uds_func_ids = sorted({r["unit"] for r in uds_rows if r["unit"]})
print(f"\nUDS 함수 인벤토리 {len(uds_func_ids)}")


def run(assign, label):
    mx = generate_uds_traceability_matrix(
        req_items, mapping_pairs=build_mapping_pairs(assign), vcast_rows=[],
        sds_pairs=sds_pairs, sits_rows=[], uds_function_ids=uds_func_ids,
        component_asil=m["component_asil"])
    rows = mx["rows"]
    per_req = [len(r.get("source_ids") or []) for r in rows]
    linked = [n for n in per_req if n]
    traced_fns = {str(s).strip().lower() for r in rows for s in (r.get("source_ids") or [])}
    print(f"\n=== {label} ===")
    print(f"  UDS 링크를 가진 요구      : {len(linked)} / {len(rows)}")
    print(f"  추적된 UDS 함수 distinct  : {len(traced_fns)} / {len(uds_func_ids)}")
    if linked:
        print(f"  요구당 함수 (중앙/평균/최대): "
              f"{statistics.median(linked):.0f} / {statistics.mean(linked):.1f} / {max(linked)}")
    print(f"  총 링크 수                : {sum(per_req)}")
    return mx, traced_fns, per_req


mx0, fn0, pr0 = run(None, "현재 (SwCom 단독 900행 브리지 불가)")
mx1, fn1, pr1 = run(opt_map, "병기 — 낙관(정확히 1개 SwFn 지정)")
mx2, fn2, pr2 = run(pes_map, "병기 — 비관(후보 SwFn 전부 나열)")

print("\n" + "=" * 66)
print(f"순증 추적 함수  낙관 +{len(fn1 - fn0)}  /  비관 +{len(fn2 - fn0)}")
print(f"총 링크 증가    낙관 +{sum(pr1) - sum(pr0)}  /  비관 +{sum(pr2) - sum(pr0)}")

json.dump({"opt": sorted(fn1 - fn0), "pes": sorted(fn2 - fn0),
           "opt_map": opt_map, "pes_map": pes_map,
           "swfn_eff": swfn_eff, "eff_swcom": eff_swcom,
           "req_norm": sorted(req_norm)},
          (SP / "effect.json").open("w", encoding="utf-8"), ensure_ascii=False)
print(f"저장: {SP / 'effect.json'}")
