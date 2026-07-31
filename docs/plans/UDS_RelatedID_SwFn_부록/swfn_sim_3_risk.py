# -*- coding: utf-8 -*-
"""병기 시뮬레이션 3/3 — 품질·위험 분해.

2/3 에서 fan-out 이 **개선이 아니라 악화**로 나왔다(23→26 낙관, 23→74 비관).
요청서는 94→25 로 개선이라 적었다. 어느 쪽이 맞는지, 무엇이 fan-out 을 정하는지 분해한다.
"""
import collections
import json
import pathlib
import statistics
import sys

SP = pathlib.Path(sys.argv[1])
base = json.loads((SP / "baseline.json").read_text(encoding="utf-8"))
eff = json.loads((SP / "effect.json").read_text(encoding="utf-8"))
uds_rows = base["uds_rows"]
swfn_eff = eff["swfn_eff"]
eff_swcom = eff["eff_swcom"]
opt_map = eff["opt_map"]

# ── 1. UDS 함수가 SwCom 에 어떻게 몰려 있나 ────────────────────────────────
per_com = collections.Counter()
for r in uds_rows:
    if r["swcoms"] and not r["design_ids"] and not r["req_direct"]:
        for c in r["swcoms"]:
            per_com[c] += 1
print("=" * 68)
print("1. SwCom 단독 900행이 SwCom 에 몰린 정도 (fan-out 의 실제 결정 요인)")
print("=" * 68)
vals = list(per_com.values())
print(f"  SwCom {len(per_com)}개에 분산 · 중앙 {statistics.median(vals):.0f} · 최대 {max(vals)}")
for c, n in per_com.most_common(8):
    nreq = len(eff_swcom.get(c, []))
    tgt = opt_map.get(c, [])
    tgt_req = len(swfn_eff.get(tgt[0], [])) if tgt else 0
    print(f"    {c:12} 함수 {n:4}  SwCom요구 {nreq:2}  →배정 {tgt[0] if tgt else '(없음)':10} 요구 {tgt_req}")

print("\n  ⟹ 한 SwCom 에 몰린 함수를 SwFn 하나로 보내면 그 SwFn 의 요구가 그만큼을 통째로 받는다.")

# ── 2. SwFn 이 실제로 몇 개 요구를 가리키나 ────────────────────────────────
print("\n" + "=" * 68)
print("2. SwFn / SwCom 의 요구 보유 폭 (요청서가 근거로 든 축)")
print("=" * 68)
fn_w = sorted(len(v) for v in swfn_eff.values())
cm_w = sorted(len(v) for v in eff_swcom.values())
print(f"  SwFn  {len(fn_w)}개 — 요구 중앙 {statistics.median(fn_w):.0f} · 최대 {max(fn_w)} · 합 {sum(fn_w)}")
print(f"  SwCom {len(cm_w)}개 — 요구 중앙 {statistics.median(cm_w):.0f} · 최대 {max(cm_w)} · 합 {sum(cm_w)}")
print("  ⟹ SwFn 이 '요구당 폭'은 좁다. 요청서의 1·6 vs 5·17 은 맞다.")
print("     그러나 매트릭스 fan-out 은 이 폭이 아니라 **함수 쏠림 × 폭** 으로 정해진다.")

# ── 3. 이상적 균등 배분이면? ────────────────────────────────────────────────
print("\n" + "=" * 68)
print("3. 팀이 900행을 SwFn 41개에 **균등** 배분한다면 (이상적 상한)")
print("=" * 68)
n_swfn = len(swfn_eff)
even = 900 / n_swfn
req_load = collections.Counter()
for d, rs in swfn_eff.items():
    for r in rs:
        req_load[r] += even
loads = sorted(req_load.values())
print(f"  SwFn 당 함수 {even:.0f}개 가정 → 요구당 함수 중앙 {statistics.median(loads):.0f} · 최대 {max(loads):.0f}")
print("  (현재 매트릭스 실측 중앙 23 · 최대 201 — 균등 배분이어도 개선이 아니라 **추가**다)")

# ── 4. 새로 추적되는 477 함수는 어떤 것들인가 ──────────────────────────────
print("\n" + "=" * 68)
print("4. 순증 477 함수의 정체")
print("=" * 68)
newly = set(eff["opt"])
by_com = collections.Counter()
name_of = {}
for r in uds_rows:
    key = str(r["unit"]).strip().lower()
    if key in newly:
        name_of.setdefault(key, r["unit"])
        for c in r["swcoms"]:
            by_com[c] += 1
print(f"  순증 {len(newly)}개 — 소속 SwCom 상위:")
for c, n in by_com.most_common(6):
    print(f"    {c:12} {n:4}개")
print(f"  샘플: {[name_of[k] for k in sorted(newly)[:6]]}")

# ── 5. 4개 미도달 요구 ──────────────────────────────────────────────────────
print("\n" + "=" * 68)
print("5. UDS 링크가 없는 요구 4건 — 병기로도 안 닿는 이유")
print("=" * 68)
req_norm = set(eff["req_norm"])
reached = {r for rs in swfn_eff.values() for r in rs} | {r for rs in eff_swcom.values() for r in rs}
print(f"  SRS 요구 {len(req_norm)} 중 SDS 설계ID/SwCom 이 가리키는 요구 {len(reached)}")
print(f"  SDS 어느 엔트리도 안 가리키는 요구 = {sorted(req_norm - reached)}")
