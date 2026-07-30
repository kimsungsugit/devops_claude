# -*- coding: utf-8 -*-
"""요청서 부록 생성 — UDS Related ID 현황(A) + SwFn 카탈로그(B).

UDS 는 함수 1개당 kv 표(좌=라벨, 우=값) 1개다. 같은 표 안에서 '함수명' 라벨과
'Related ID' 라벨을 짝지어 뽑는다.
"""
import collections
import io
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
)

BASE = ("U:/연구소/1000 프로젝트/1200 자동차/1220 진행/0002 A Cappella/02 ADOS/04 KJPDS02/"
        "02.설계(연구소)/01.설계 및 검증/08.소프트웨어/")
UDS = BASE + "04.SW 단위 설계/01.SwUDS/(KJPDS02_SwUDS) Software Unit Design Specification_v3.02_260XXX.docx"
SDS = BASE + "03.SW 아키텍처 설계/01.SwDS/(KJPDS02_SwDS) Software Architecture Design Specification_v3.01_20260410_R.docx"
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")

TBL = re.compile(r"<w:tbl[ >].*?</w:tbl>", re.S)
ROW = re.compile(r"<w:tr[ >].*?</w:tr>", re.S)
CELL = re.compile(r"<w:tc[ >].*?</w:tc>", re.S)
T = re.compile(r"<w:t[^>]*>(.*?)</w:t>", re.S)
DESIGN_RE = re.compile(r"\bSw(?:Com|Fn|STR|ST|TK|UFn)_?\s*\d+", re.I)
SWCOM_ONLY = re.compile(r"^\s*(?:SwCom_?\s*\d+\s*[,;/]?\s*)+$", re.I)


def txt(frag):
    return " ".join(re.sub(r"<[^>]+>", "", "".join(T.findall(frag))).split()).strip()


def read(path):
    r = CloudiumFileResolver(allowed_prefixes=path.rsplit("/", 1)[0])
    return r.read_bytes(path)


# ── 부록 A: UDS 함수별 Related ID ────────────────────────────────────────────
xml = zipfile.ZipFile(io.BytesIO(read(UDS))).read("word/document.xml").decode("utf-8", "ignore")

rows_a = []
label_seen = collections.Counter()
for tbl in TBL.finditer(xml):
    kv = {}
    order = []
    for row in ROW.finditer(tbl.group(0)):
        cells = [txt(c.group(0)) for c in CELL.finditer(row.group(0))]
        if len(cells) < 2:
            continue
        lab = cells[0].lower()
        val = next((x for x in cells[1:] if x), "")
        if lab and lab not in kv:
            kv[lab] = val
            order.append(lab)
        label_seen[lab] += 1
    rel_key = next((k for k in order if re.search(r"related", k)), "")
    if not rel_key:
        continue
    # SwUFn ID(문서 행 키)와 함수명(팀이 SwFn 을 배정할 실제 단서)을 **둘 다** 싣는다.
    rows_a.append({
        "uid": kv.get("id", ""),
        "unit": kv.get("name", "") or kv.get("unit name", "") or kv.get("함수명", ""),
        "proto": kv.get("prototype", "")[:70],
        "related": kv.get(rel_key, ""),
    })

print(f"UDS Related 표 {len(rows_a)}건 / 함수명 확보 {sum(1 for r in rows_a if r['unit'])}"
      f" / SwUFn ID 확보 {sum(1 for r in rows_a if r['uid'])}")
print("좌측 라벨 상위 12:", label_seen.most_common(12))

swcom_only = [r for r in rows_a if r["related"] and SWCOM_ONLY.match(r["related"])]
bridgeable = [r for r in rows_a if r["related"] and not SWCOM_ONLY.match(r["related"])
              and DESIGN_RE.search(r["related"])]
empty = [r for r in rows_a if not r["related"].strip()]
print(f"  SwCom 단독 : {len(swcom_only)} ({len(swcom_only)/max(len(rows_a),1)*100:.1f}%)")
print(f"  브리지 가능 : {len(bridgeable)} ({len(bridgeable)/max(len(rows_a),1)*100:.1f}%)")
print(f"  빈 값       : {len(empty)}")

# ── 부록 B: SDS SwFn 카탈로그 ────────────────────────────────────────────────
with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
    tf.write(read(SDS))
    tmp = tf.name
pm = _extract_sds_partition_map(tmp)
pathlib.Path(tmp).unlink(missing_ok=True)

REQ_RE = re.compile(r"\bSw(?:TR|EI|TSR|NTR|CNF)_?\d+", re.I)
FN_RE = re.compile(r"^sw_?fn_?\d+$", re.I)
swfn = {}
for name, info in pm.items():
    key = _normalize_req_id(name)
    if not FN_RE.match(key):
        continue
    reqs = sorted({_normalize_req_id(x) for x in REQ_RE.findall(str(info.get("related") or ""))})
    # TSV 는 행 단위라 설명의 줄바꿈·탭을 반드시 접는다. 절단은 '…' 로 표면화(침묵 금지).
    _d = " ".join(str(info.get("description") or "").split())
    swfn[key] = {"reqs": reqs, "desc": (_d[:110] + "…") if len(_d) > 110 else _d,
                 "asil": str(info.get("asil") or "")}
print(f"\nSwFn 카탈로그 {len(swfn)}건 / 요구 보유 {sum(1 for v in swfn.values() if v['reqs'])}")
print(f"  ASIL 표기 보유 {sum(1 for v in swfn.values() if v['asil'])}")

# ── TSV 출력 ────────────────────────────────────────────────────────────────
OUT.mkdir(parents=True, exist_ok=True)
with (OUT / "appendix_A_swcom_only.tsv").open("w", encoding="utf-8-sig", newline="") as f:
    f.write("SwUFn ID\t함수명\tPrototype(발췌)\t현재 Related ID\t추가할 SwFn (팀 기입)\n")
    for r in swcom_only:
        f.write(f"{r['uid']}\t{r['unit']}\t{r['proto']}\t{r['related']}\t\n")


def _num(k):
    m = re.search(r"\d+", k)
    return int(m.group()) if m else 0


with (OUT / "appendix_B_swfn_catalog.tsv").open("w", encoding="utf-8-sig", newline="") as f:
    f.write("SwFn ID\tASIL\t연결 요구ID\t설명(발췌)\n")
    for k in sorted(swfn, key=_num):
        v = swfn[k]
        f.write(f"{k}\t{v['asil'] or '-'}\t{', '.join(v['reqs']) or '-'}\t{v['desc']}\n")
print(f"\n출력: {OUT/'appendix_A_swcom_only.tsv'} ({len(swcom_only)}행)")
print(f"      {OUT/'appendix_B_swfn_catalog.tsv'} ({len(swfn)}행)")
