"""`reports/` 누적 파일을 **지우지 않고 분류**한다 (R44 N13).

사용자 결정(2026-09-09): *"식별 규칙부터 만들어 보고"* — 삭제는 이 스크립트가 하지 않는다.

## 왜 규칙이 필요한가

`reports/` 는 실물 산출물과 테스트 산물이 같은 트리에 쌓여 있다. R38 이 격리를 넣어
**신규 유출은 멈췄지만** 그 이전 6개월치는 섞인 채 남아 있고, 화면(`build_timeline`)과
AI 인사이트가 이 트리를 읽는다.

## 축 셋 — 하나로는 못 가른다

1. **활동 여부**(마지막 파일 시각). 3~4월에 멈춘 디렉터리는 옛 개발 유물이지 테스트가
   계속 쌓는 것이 아니다. 조치가 다르므로 먼저 가른다.
2. **격리 전/후**. R38 격리(2026-09-08) 이후 생긴 파일은 **테스트가 만들 수 없다** —
   그 구간이 '실물의 모양' 기준선이다.
3. **내용의 실물 서명**(결정적). 레지스트리의 실제 `scm_id` 나 소스 루트 경로가 파일
   **안에** 들어 있는가. 파일명보다 훨씬 강하다.

⚠ 첫 판은 축 하나(파일명 앞부분을 scm_id 로 해석)만 썼고 **83%가 '미상'** 이 나와
아무것도 못 갈랐다. 축 3이 들어오자 갈렸다 — `impact_changes` 400/400 · `impact_audit`
366/366 이 서명을 갖는 반면 `uds` 1/400 · `qac_impact` 1/400 이다. 후자는 R38 이 독립
경로로 낸 판정("qac_impact 1,586 중 1,585 가 테스트 산물")과 일치한다.

사용법: `.venv/Scripts/python.exe scripts/triage_reports_tree.py [--sample N]`
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import time
from typing import Dict, List, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

#: R38 이 `reports/` 세션 격리를 넣은 **시각**. 이후 생성분은 테스트가 만들 수 없다.
#: ⚠ (R44 리뷰 W1) 처음엔 날짜만 적어 자정으로 해석됐다. 격리 커밋 `e4822e3b` 는 그날
#:   **14:50**, 두 번째 트리 격리 `6281c9e2` 는 16:55 다. 자정 기준이면 같은 날 오전에
#:   테스트가 만든 파일이 "테스트가 만들 수 없는 것" 으로 계상된다 — 실제로 `reports/uds`
#:   의 '격리후' 20건이 전부 `pytest-…` 경로를 담은 픽스처였다(그 열이 의미를 갖는 유일한
#:   날에 100% 오분류). 늦은 쪽(두 번째 격리) 시각을 쓴다.
ISOLATION_AT = "2026-09-08 16:55"
#: 이 일수 안에 파일이 생겼으면 '활동중'.
LIVE_DAYS = 30
#: 서명 검사 표본 상한(디렉터리당). 전수는 수만 파일이라 느리다.
DEFAULT_SAMPLE = 400
#: 이보다 큰 파일은 서명 검사에서 건너뛴다(읽기 비용).
MAX_READ_BYTES = 2_000_000

#: 텍스트로 판독할 수 없는 확장자 — 서명이 **구조적으로** 안 잡히므로 분모에서 뺀다.
#: ⚠ (R44 리뷰 C1) 이것이 이 스크립트의 가장 위험했던 결함이다. `errors="ignore"` 로
#:   PNG 를 읽으면 서명은 절대 안 맞는데 그 파일도 분모에 들어갔다. `reports/uds_local`
#:   2,192개 중 PNG 가 **1,712개(78%)** 라 전체 비율이 1.5% 로 눌려 **"테스트 산물 유력"**
#:   이 됐지만, 판독 가능한 JSON 194개만 보면 서명 보유가 **11.4%** 로 "혼재" 다.
#:   그 표를 보고 지웠다면 실물이 섞인 2,192개가 근거 없이 삭제 후보가 됐다.
#:   **판독 불가는 '서명 없음' 이 아니라 '판정 불가' 다.**
_BINARY_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svgz",
    ".zip", ".gz", ".7z", ".xz", ".bz2", ".tar",
    ".xlsx", ".xlsm", ".xls", ".docx", ".doc", ".pptx", ".pdf",
    ".sqlite", ".db", ".pyc", ".pyd", ".dll", ".exe", ".so", ".o", ".obj",
})


def _real_signatures() -> Tuple[List[str], List[str]]:
    """레지스트리에서 실물 서명을 읽는다 — 손으로 적으면 프로젝트가 늘 때 반드시 빠진다.

    ⚠ `config/scm_registry.json` 은 **사용자 데이터**다. 읽기만 한다.
    """
    try:
        reg = json.loads((ROOT / "config" / "scm_registry.json").read_text("utf-8"))
    except (OSError, ValueError):
        return [], []
    ids, roots = [], []
    for entry in reg.get("registries", []) or []:
        if entry.get("id"):
            ids.append(str(entry["id"]).lower())
        for part in str(entry.get("source_root") or "").replace("/", "\\").split(","):
            part = part.strip().lower()
            if not part:
                continue
            roots.append(part)
            # ⚠ (R44 리뷰 W3) JSON 본문의 경로는 `"D:\\Project\\..."` 로 **이스케이프**돼 있어
            #   원본 서명(`d:\project\...`)과 절대 안 맞는다 — 실측: `reports/uds` JSON 120개 중
            #   히트 0, 히트는 전부 `.md` 에서 나왔다. 선언한 2축 중 하나가 죽어 있던 셈이라
            #   "테스트 산물" 쪽으로 편향됐다. 이스케이프 판과 마지막 세그먼트를 함께 넣는다.
            roots.append(part.replace("\\", "\\\\"))
            tail = part.rstrip("\\").rsplit("\\", 1)[-1]
            if len(tail) >= 4:
                roots.append(tail)
    return ids, sorted(set(roots))


def _walk(dir_path: str) -> List[pathlib.Path]:
    out: List[pathlib.Path] = []
    for dirpath, _dirnames, filenames in os.walk(dir_path):
        for name in filenames:
            out.append(pathlib.Path(dirpath) / name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                    help=f"디렉터리당 서명 검사 표본 수 (기본 {DEFAULT_SAMPLE}, 0=전수)")
    ap.add_argument("--seed", type=int, default=7, help="무작위 표본 seed (재현용, 기본 7)")
    args = ap.parse_args()

    if not REPORTS.is_dir():
        print("reports/ 가 없습니다.")
        return 0

    ids, roots = _real_signatures()
    if not ids and not roots:
        # 서명을 못 읽으면 **판정하지 않는다** — 전부 '테스트 산물' 로 보이는 것이 최악이다.
        print("⚠ 레지스트리에서 실물 서명을 읽지 못했습니다 — 서명 축 없이는 판정하지 않습니다.")
        return 1
    print(f"실물 서명: scm_id {ids} · 소스 루트 {len(roots)}개")

    isolation_ts = time.mktime(time.strptime(ISOLATION_AT, "%Y-%m-%d %H:%M"))
    now = time.time()

    rows = []
    for entry in sorted(os.scandir(REPORTS), key=lambda e: e.name):
        if not entry.is_dir(follow_symlinks=False):
            continue
        files = _walk(entry.path)
        times = []
        for p in files:
            try:
                times.append(p.stat().st_mtime)
            except OSError:
                continue
        if not times:
            continue
        rows.append({
            "name": entry.name,
            "files": files,
            "count": len(files),
            "newest": max(times),
            "after_isolation": sum(1 for t in times if t >= isolation_ts),
        })

    print()
    print(f"{'하위':24s} {'파일':>8s} {'마지막':>8s} {'격리후':>7s}  상태")
    print("-" * 74)
    live, dormant = [], []
    for row in sorted(rows, key=lambda r: -r["count"]):
        age = (now - row["newest"]) / 86400
        state = "활동중" if age < LIVE_DAYS else ("멈춤" if age < 120 else "유물")
        (live if age < LIVE_DAYS else dormant).append(row)
        print(f"{row['name']:24s} {row['count']:8,d} "
              f"{time.strftime('%m-%d', time.localtime(row['newest'])):>8s} "
              f"{row['after_isolation']:7d}  {state}")
    print("-" * 74)
    print(f"활동중 {sum(r['count'] for r in live):,}개 · "
          f"멈춤/유물 {sum(r['count'] for r in dormant):,}개 · "
          f"합계 {sum(r['count'] for r in rows):,}개")

    print()
    print(f"=== 활동중 디렉터리의 내용 서명 (무작위 표본 {args.sample or '전수'}, seed={args.seed}) ===")
    print(f"{'하위':24s} {'판독':>6s} {'서명':>6s} {'없음':>6s} {'불가':>6s}  {'표본 시각':<13s} 판정")
    print("-" * 94)
    verdict: Dict[str, str] = {}
    for row in live:
        files = row["files"]
        if args.sample and len(files) > args.sample:
            # ⚠ (리뷰 W2) `files[:N]` 은 walk 순서(사실상 생성순)라 앞머리만 본다 —
            #   `uds` 표본의 mtime 이 02~06월인데 디렉터리는 09월까지 뻗어 있었다.
            sample = random.Random(args.seed).sample(files, args.sample)
        else:
            sample = list(files)

        hit = readable = 0
        unreadable = 0          # 이진·초대형·읽기 실패 = **판정 불가**(서명 없음이 아니다)
        stamps = []
        for p in sample:
            try:
                st = p.stat()
            except OSError:
                unreadable += 1
                continue
            stamps.append(st.st_mtime)
            if p.suffix.lower() in _BINARY_SUFFIXES or st.st_size > MAX_READ_BYTES:
                unreadable += 1
                continue
            try:
                raw = p.read_bytes()
            except OSError:
                unreadable += 1
                continue
            if b"\x00" in raw[:4096]:   # NUL 이 있으면 이진 = 판독 불가
                unreadable += 1
                continue
            text = raw.decode("utf-8", errors="ignore").lower()
            readable += 1
            if any(sig in text for sig in ids) or any(sig in text for sig in roots):
                hit += 1

        span = ""
        if stamps:
            span = (f"{time.strftime('%m-%d', time.localtime(min(stamps)))}"
                    f"~{time.strftime('%m-%d', time.localtime(max(stamps)))}")
        if not readable:
            note = f"판정 불가(판독 0/{len(sample)})"
        elif hit / readable >= 0.8:
            note = "실물 유력"
        elif hit / readable <= 0.05:
            note = "테스트 산물 유력"
        else:
            note = "혼재 — 개별 확인 필요"
        # 판독 비율이 낮으면 그 사실을 판정에 **붙여서** 낸다 — 근거의 두께가 곧 신뢰도다.
        if readable and unreadable and readable / (readable + unreadable) < 0.5:
            note += f" ⚠판독 {readable}/{readable + unreadable}"
        verdict[row["name"]] = note
        print(f"{row['name']:24s} {readable:6d} {hit:6d} {readable - hit:6d} {unreadable:6d}  "
              f"{span:<13s} {note}")

    print()
    print("=== 요약 ===")
    buckets: Dict[str, int] = {}
    for row in live:
        buckets[verdict.get(row["name"], "?")] = \
            buckets.get(verdict.get(row["name"], "?"), 0) + row["count"]
    for note, n in sorted(buckets.items(), key=lambda kv: -kv[1]):
        print(f"  {note:20s} {n:8,d}개")
    print(f"  {'멈춤/유물(옛 개발)':20s} {sum(r['count'] for r in dormant):8,d}개"
          f"  ← **서명 미검사**(mtime 단독 판정)")
    print()
    print("⚠ 이 스크립트는 **세기만 한다**. 삭제는 사람의 판단이다.")
    print(f"⚠ 위 판정은 **디렉터리당 최대 {args.sample}개 무작위 표본**의 결과다 — 절대수는"
          " 표본이 아니라 전체 파일 수다. 지우기 전에 `--sample 0`(전수)으로 다시 세고,"
          " '판정 불가'·'혼재'·'멈춤/유물' 은 개별 확인 후 백업할 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
