# -*- coding: utf-8 -*-
"""부록 C — SDS 에는 설계로 남았으나 UDS 에 없는 함수(문서-코드 드리프트) 목록.

분류 기준은 **소스 원문**이다:
  IMPL_ACTIVE   .c 에 정의가 살아 있고 헤더 선언도 살아 있음 → UDS 누락(진짜 갭)
  DECL_COMMENT  .c 에 정의는 있으나 헤더 선언이 주석 처리 → 사장된 코드가 SDS 에 잔존
  NO_IMPL       소스에 정의 자체가 없음 → 설계만 있고 구현 없음
"""
import io
import pathlib
import re
import sys
import tempfile
import zipfile

sys.path.insert(0, str(pathlib.Path.cwd()))
from backend.services.file_resolver import CloudiumFileResolver  # noqa: E402
from report_gen.requirements import _extract_sds_partition_map  # noqa: E402

BASE = ("U:/연구소/1000 프로젝트/1200 자동차/1220 진행/0002 A Cappella/02 ADOS/04 KJPDS02/"
        "02.설계(연구소)/01.설계 및 검증/08.소프트웨어/")
UDS = BASE + "04.SW 단위 설계/01.SwUDS/(KJPDS02_SwUDS) Software Unit Design Specification_v3.02_260XXX.docx"
SDS = BASE + "03.SW 아키텍처 설계/01.SwDS/(KJPDS02_SwDS) Software Architecture Design Specification_v3.01_20260410_R.docx"
SRC_ROOTS = [pathlib.Path(r"C:/Project/Ados/NE1AW_PORTING"), pathlib.Path(r"C:/Project/Ados/PDS128_FBL")]
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")


def read(path):
    return CloudiumFileResolver(allowed_prefixes=path.rsplit("/", 1)[0]).read_bytes(path)


# ── UDS 함수명 집합 ─────────────────────────────────────────────────────────
xml = zipfile.ZipFile(io.BytesIO(read(UDS))).read("word/document.xml").decode("utf-8", "ignore")
T = re.compile(r"<w:t[^>]*>(.*?)</w:t>", re.S)
CELL = re.compile(r"<w:tc[ >].*?</w:tc>", re.S)
ROW = re.compile(r"<w:tr[ >].*?</w:tr>", re.S)


def txt(frag):
    return " ".join(re.sub(r"<[^>]+>", "", "".join(T.findall(frag))).split()).strip()


uds_names = set()
for row in ROW.finditer(xml):
    cells = [txt(c.group(0)) for c in CELL.finditer(row.group(0))]
    if len(cells) >= 2 and cells[0].strip().lower() == "name":
        v = next((x for x in cells[1:] if x), "")
        if v:
            uds_names.add(v.strip().lower())
print(f"UDS 함수명 {len(uds_names)}")

# ── SDS 함수 엔트리 ─────────────────────────────────────────────────────────
with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
    tf.write(read(SDS))
    tmp = tf.name
pm = _extract_sds_partition_map(tmp)
pathlib.Path(tmp).unlink(missing_ok=True)
sds_funcs = sorted(k for k, v in pm.items() if v.get("kind") == "function")
print(f"SDS 함수 엔트리 {len(sds_funcs)}")

missing = [f for f in sds_funcs if f not in uds_names]
print(f"SDS ∧ ¬UDS = {len(missing)}")

# ── 소스 대조 ───────────────────────────────────────────────────────────────
src_files = []
for root in SRC_ROOTS:
    if root.exists():
        src_files += [p for p in root.rglob("*.c")] + [p for p in root.rglob("*.h")]
print(f"소스 파일 {len(src_files)}")
_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_LINE = re.compile(r"//[^\n]*")


def _strip_comments(s):
    """주석을 **길이 보존**하며 공백으로 치환 — 오프셋이 어긋나면 행번호가 틀어진다."""
    s = _BLOCK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), s)
    return _LINE.sub(lambda m: " " * len(m.group(0)), s)


blobs = {}
for p in src_files:
    try:
        raw = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    blobs[p] = (raw, _strip_comments(raw))


def classify(fn):
    """(분류, 근거) — 정의 위치와 헤더 선언의 주석 여부.

    주석 판정은 **주석 제거본과의 대조**로 한다. 라인 주석(`//`)만 보던 이전 판정은
    블록 주석(`/* ... */`)으로 통째 막힌 선언을 살아 있는 것으로 읽었다.
    """
    def_pat = re.compile(r"^[^\S\n]*(?:\w[\w\s\*]*?)\b" + re.escape(fn) + r"\s*\([^;]*?\)\s*\{",
                         re.M | re.I)
    decl_pat = re.compile(r"\b" + re.escape(fn) + r"\s*\([^\n]*?\)\s*;", re.M | re.I)
    hit_def, hit_decl, hit_decl_commented = "", "", ""
    for p, (raw, bare) in blobs.items():
        if fn.lower() not in raw.lower():
            continue
        if p.suffix == ".c" and not hit_def and def_pat.search(bare):
            hit_def = p.name
        for m in decl_pat.finditer(raw):
            # 같은 오프셋이 주석 제거본에서도 비어 있지 않으면 살아 있는 선언.
            alive = bare[m.start():m.end()].strip() != ""
            if alive:
                hit_decl = hit_decl or p.name
            else:
                hit_decl_commented = hit_decl_commented or \
                    f"{p.name}:{raw[:m.start()].count(chr(10)) + 1}"
    if hit_def and hit_decl:
        return "IMPL_ACTIVE", f"정의 {hit_def} / 선언 {hit_decl}"
    if hit_def and hit_decl_commented:
        return "DECL_COMMENT", f"정의 {hit_def} / 선언 주석처리 {hit_decl_commented}"
    if hit_def:
        return "IMPL_NO_DECL", f"정의 {hit_def} / 헤더 선언 미발견"
    if hit_decl_commented:
        return "DECL_COMMENT_NO_IMPL", f"선언 주석처리 {hit_decl_commented} / 정의 없음"
    return "NO_IMPL", "소스에 정의 없음"


rows = [(fn, *classify(fn)) for fn in missing]
OUT.mkdir(parents=True, exist_ok=True)
with (OUT / "appendix_C_doc_code_drift.tsv").open("w", encoding="utf-8-sig", newline="") as f:
    f.write("SDS 함수\t분류\t소스 근거\n")
    for fn, cls, why in sorted(rows, key=lambda r: (r[1], r[0])):
        f.write(f"{fn}\t{cls}\t{why}\n")

import collections  # noqa: E402

print("분류:", dict(collections.Counter(c for _, c, _ in rows)))
for fn, cls, why in sorted(rows, key=lambda r: (r[1], r[0]))[:20]:
    print(f"  [{cls:13}] {fn}  — {why}")
print(f"\n출력: {OUT/'appendix_C_doc_code_drift.tsv'} ({len(rows)}행)")
