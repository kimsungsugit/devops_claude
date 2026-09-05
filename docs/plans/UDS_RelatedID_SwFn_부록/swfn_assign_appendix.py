# -*- coding: utf-8 -*-
"""부록 A(앱 계층 배정 대상) · 부록 D(범위 경계 제외 근거) 생성.

`swfn_sim_1_baseline.py` 를 먼저 돌려 `baseline.json` 을 만든 뒤 실행한다.

    .venv/Scripts/python.exe swfn_sim_1_baseline.py <작업디렉터리>/baseline.json
    .venv/Scripts/python.exe swfn_assign_appendix.py <작업디렉터리> <출력디렉터리>

## 왜 900행이 아니라 390행인가

초판 부록 A 는 SwCom 단독 900행을 통째로 요청 대상으로 삼았다. 실측하니

  254행  함수명이 SDS 함수 엔트리와 일치해 **이미 추적 중** → 요청 불필요
  646행  순증 후보
    ├ APP_LEAF    390  ← 실제 요청 대상
    └ 인프라       256  BOOT_REPROG 154 · BSW_DRIVER 74 · LIB_UTIL 28

부트로더 flash 루틴(`EraseFlashSector`)이나 SPI 드라이버(`s_DrvIn_SPI_WriteDrv8706`)에
앱 설계ID(SwFn)를 붙이면 "부트로더가 Assist Close 요구를 구현한다"는 **거짓 추적**이 된다.
그래서 인프라는 대상에서 빼되 **왜 뺐는지 근거를 부록 D 로 남긴다** — 감사에서 '누락'이
아니라 '의도적 범위 경계'임을 증명해야 하기 때문이다.

⚠ 계층 판정(`_classify_unmapped_layer`)은 저장소에서 **순수 표시 힌트** 계약으로 쓰이는
휴리스틱이다. 확정이 아니므로 부록 D 에 판정 근거 토큰까지 실어 팀이 되돌릴 수 있게 한다.

## SwFn 후보 열에 대해 — 어디까지 좁혀지는지 정직하게

"어느 함수가 어느 SwFn 인가"는 설계 의도라 도구가 정할 수 없다. 다만 SwCom 의 요구집합과
겹치는 SwFn 을 **열거**하는 것은 추정이 아니라 선택지를 좁히는 것이다. 좁은 순 정렬은
읽기 편의일 뿐 권고 순위가 아니다.

⚠ **다만 이 방법이 실제로 좁혀주는 행은 일부다.** SwCom 이 요구를 많이 가질수록 교집합이
커져 후보가 SwFn 목록 전체에 가까워진다. 실측 분포(앱 390행):

    후보 0개      6행   → 검토 필요
    후보 1~6개  103행   → 실질적으로 좁혀짐
    후보 7개+   281행   → **좁히지 못함**(SwCom 요구 폭이 넓어서)

그래서 후보 7개 이상인 행은 목록을 싣되 비고에 "좁히지 못함"을 **명시**한다. 18개를
나열해 놓고 '후보'라 부르면 팀이 앞의 것을 고르게 되므로(anchoring) 그렇게 두지 않는다.

더 나은 신호를 찾아봤으나 문서에 없다 — SwFn 설명에 UDS 함수명이 적힌 경우 **0/390**,
설명 단어 ↔ 함수명 토큰 매칭도 355/390(91%)이 무매칭이었다.
"""
import collections
import json
import pathlib
import re
import statistics
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path.cwd()))
from backend.services.file_resolver import CloudiumFileResolver  # noqa: E402
from report_gen.requirements import (  # noqa: E402
    _classify_unmapped_layer,
    _docx_to_text,
    _normalize_req_id,
    _safe_docx_open,
    _sds_comp_key,
    generate_uds_requirements_preview,
)

BASE = ("U:/연구소/1000 프로젝트/1200 자동차/1220 진행/0002 A Cappella/02 ADOS/04 KJPDS02/"
        "02.설계(연구소)/01.설계 및 검증/08.소프트웨어/")
SRS = BASE + "01.SW 요구사항/01.SwRS/(KJPDS02_SwRS) Software Requirements Specification_v3.01_20260410_R.docx"

WORK = pathlib.Path(sys.argv[1])
OUT = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else sys.argv[1])
base = json.loads((WORK / "baseline.json").read_text(encoding="utf-8"))
uds_rows = base["uds_rows"]
sds_fn_keys = set(base["sds_fn_keys"])

REQ_NS = re.compile(r"^SW(?:TR|TSR|NTR|NTSR|CNF|EI)_\d+$")
# 여러 기능이 공유하는 범용 산술/유틸 — 단일 SwFn 배정이 부적절할 수 있어 따로 표시한다.
GENERIC_RE = re.compile(
    r"(guarded|countup|_add_|_mul_|_sub_|_div_|copydata|dataset|memcpy|memset|"
    r"checksum|crc|clamp|limit|minmax|abs_)", re.I)


def read(path):
    return CloudiumFileResolver(allowed_prefixes=path.rsplit("/", 1)[0]).read_bytes(path)


# ── SRS 요구 universe (브리지에 유효한 설계ID/SwCom 을 가리는 기준) ────────────
with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
    tf.write(read(SRS))
    _srs_tmp = tf.name
_items = generate_uds_requirements_preview([_docx_to_text(_safe_docx_open(_srs_tmp))])["items"]
pathlib.Path(_srs_tmp).unlink(missing_ok=True)
req_norm = {_normalize_req_id(str(i["id"])) for i in _items if str(i.get("id") or "").strip()}
print(f"SRS 요구 {len(req_norm)}")


def _effective(mapping):
    """SDS 엔트리 → 매트릭스 SRS 요구에 **실제로 닿는** 것만 남긴다."""
    out = {}
    for k, reqs in mapping.items():
        hit = [r for r in reqs if r in req_norm]
        if hit:
            out[k] = hit
    return out


swfn_eff = _effective({k: v for k, v in base["design_to_reqs"].items() if k.startswith("SWFN_")})
swcom_eff = _effective(base["swcom_to_reqs"])
print(f"브리지 유효 SwFn {len(swfn_eff)} · SwCom {len(swcom_eff)}")

# SwCom → SwFn 후보 (요구집합 교집합). 좁은 순 = 읽기 편의, 권고 아님.
cand_map = {}
for com, creqs in swcom_eff.items():
    cs = set(creqs)
    cands = sorted(((len(rs), d) for d, rs in swfn_eff.items() if cs & set(rs)))
    if cands:
        cand_map[com] = [d for _, d in cands]

# ── 요청 대상 산정 ──────────────────────────────────────────────────────────
only = [r for r in uds_rows if r.get("unit") and r["swcoms"]
        and not r["design_ids"] and not r["req_direct"]]
named = {r["unit"] for r in only if _sds_comp_key(r["unit"]) in sds_fn_keys}
cand_rows = [r for r in only if r["unit"] not in named]
print(f"\nSwCom 단독 {len(only)} = 이름일치 {len(only) - len(cand_rows)} + 순증후보 {len(cand_rows)}")

app_rows, infra_rows = [], []
for r in cand_rows:
    (app_rows if _classify_unmapped_layer([r["unit"]]) == "APP_LEAF" else infra_rows).append(r)
print(f"  APP {len(app_rows)} / 인프라 {len(infra_rows)}")


def _tsv(path, header, rows):
    """TSV 기록 + 열 수 계약 검증(과거 CSV 열 밀림 전례 — 헤더와 전 행이 같아야 한다)."""
    ncol = len(header)
    bad = [i for i, r in enumerate(rows) if len(r) != ncol]
    if bad:
        raise SystemExit(f"열 수 불일치 {path.name}: 헤더 {ncol}, 행 {bad[:5]}")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(" ".join(str(c or "").split()) for c in r) + "\n")
    print(f"  {path.name}: {len(rows)}행 × {ncol}열")


OUT.mkdir(parents=True, exist_ok=True)

# ── 부록 A ─────────────────────────────────────────────────────────────────
# 후보가 이보다 많으면 '좁혀준 것'이 아니다 — 실측 분포에서 6과 10 사이가 비어 있다.
NARROW_MAX = 6
no_cand = generic = wide = 0
a_rows = []
for r in sorted(app_rows, key=lambda x: (x["swcoms"][0] if x["swcoms"] else "", x["unit"].lower())):
    com = r["swcoms"][0] if r["swcoms"] else ""
    cands = cand_map.get(com, [])
    notes = []
    if not cands:
        notes.append("후보 없음 — 검토 필요")
        no_cand += 1
    elif len(cands) > NARROW_MAX:
        # 목록은 싣되 '좁혀졌다'고 오독하지 않게 명시한다(anchoring 방지).
        notes.append(f"후보 {len(cands)}개 — 도구가 좁히지 못함(SwCom 요구 폭이 넓음). 설계 판단 필요")
        wide += 1
    if GENERIC_RE.search(r["unit"]):
        notes.append("공용 — 여러 기능이 쓰므로 단일 SwFn 부적절 가능")
        generic += 1
    a_rows.append([r.get("uid", ""), r["unit"], r.get("proto", ""), "APP", com,
                   ", ".join(cands), " / ".join(notes), ""])

_tsv(OUT / "appendix_A_swcom_only.tsv",
     ["SwUFn ID", "함수명", "Prototype(발췌)", "계층", "현재 Related ID",
      "SwFn 후보 (검증 후 택1)", "비고", "팀 확정"], a_rows)
print(f"    후보 0개 행 {no_cand} · 공용 표시 {generic}")

# ── 부록 D ─────────────────────────────────────────────────────────────────
# 사유는 **행 안에서 자립**해야 한다. TSV 는 정렬·필터로 흩어지므로 "위 주석 참조" 류는
# 곧 끊어진 참조가 된다.
_REASON = {
    "BOOT_REPROG": "부트로더·재프로그래밍(flash/EEPROM) — 앱 기능 설계(SwFn)의 대상이 아님",
    "BSW_DRIVER": "기본 SW 드라이버(타이머/SPI/포트/ISR) — 앱 기능 설계(SwFn)의 대상이 아님",
    "LIB_UTIL": "범용 라이브러리(해시/문자열/유틸) — 앱 기능 설계(SwFn)의 대상이 아님",
}
d_rows = []
for r in sorted(infra_rows, key=lambda x: (_classify_unmapped_layer([x["unit"]]), x["unit"].lower())):
    lay = _classify_unmapped_layer([r["unit"]])
    d_rows.append([r.get("uid", ""), r["unit"], r["swcoms"][0] if r["swcoms"] else "", lay,
                   _REASON.get(lay, "앱 기능 설계(SwFn)의 대상이 아님")])
_tsv(OUT / "appendix_D_scope_boundary.tsv",
     ["SwUFn ID", "함수명", "현재 Related ID",
      "계층(자동판정 — 휴리스틱이며 확정 아님, 오분류 발견 시 알려주십시오)", "제외 사유"], d_rows)

# ── 검증 ────────────────────────────────────────────────────────────────────
print("\n검증")
a_names = {r[1] for r in a_rows}
d_names = {r[1] for r in d_rows}
print(f"  V1 부록A {len(a_rows)}행 · 계층 전부 APP: {all(r[3] == 'APP' for r in a_rows)}")
print(f"  V2 부록D {len(d_rows)}행 · APP 0건: {sum(1 for r in d_rows if r[3] == 'APP') == 0}")
print(f"  V3 A∪D == 순증후보: {len(a_names | d_names) == len({r['unit'] for r in cand_rows})}"
      f" · A∩D == 0: {not (a_names & d_names)}")
print(f"  V4 후보 0개 {no_cand} · 좁히지 못함(7개+) {wide} · 공용 표시 {generic}")
_narrow = len(a_rows) - no_cand - wide
print(f"     ⟹ 후보 열이 실제로 좁혀준 행 = {_narrow} / {len(a_rows)}"
      f" ({_narrow / len(a_rows) * 100:.0f}%)")
_dist = collections.Counter(len(r[5].split(", ")) if r[5] else 0 for r in a_rows)
print(f"     후보 수 분포: {dict(sorted(_dist.items()))}")
_c = [len(v) for v in cand_map.values()]
print(f"  V6 SwCom당 후보 중앙 {statistics.median(_c):.0f} · 최대 {max(_c)}")
per = collections.Counter(r[4] for r in a_rows)
top3 = sum(n for _, n in per.most_common(3))
print(f"  V7 앱 {len(a_rows)}행 / SwCom {len(per)}개 / 상위3 {top3} ({top3 / len(a_rows) * 100:.0f}%)")
print(f"     상위: {per.most_common(5)}")
print(f"  D 계층 분포: {dict(collections.Counter(r[3] for r in d_rows))}")
