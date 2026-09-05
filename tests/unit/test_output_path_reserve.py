# -*- coding: utf-8 -*-
"""산출물 경로 선점 — 같은 초에 만든 두 산출물이 서로를 덮어쓰지 않는가.

인계 문서 P6. 산출물 경로는 전부 `%Y%m%d_%H%M%S` — **초 단위**다. 같은 키(job/카테고리)
요청 둘이 같은 초에 경로를 조립하면 **완전히 같은 경로**가 나오고 마지막 쓰기만 남는다.
ISO 26262 산출물에서 이건 단순 덮어쓰기가 아니라 **A 가 받은 STS 가 실은 B 의 것**이 되는
일이고, 어디에도 흔적이 안 남는다. 키가 없는 이름(`suts_vectorcast_{ts}`)은 서로 다른
프로젝트·사용자여도 부딪힌다.

## 고정하는 계약

  A. 충돌이 **없으면 이름이 오늘과 같다** — 랜덤 접미사로 전부 바꾸지 않는다
  B. 충돌하면 `_2`, `_3` … 으로 비켜가고 **기존 파일을 건드리지 않는다**
  C. 확장자를 보존한다 (`.xlsm` 이 `.xlsx` 가 되면 산출물 종류가 바뀐다)
  D. **원자적**이다 — `exists()` 로 보고 쓰는 방식은 두 요청이 같은 순간 '없음'을 봐
     정작 막으려던 경합을 남긴다(TOCTOU)
  E. 상한까지 점유되면 조용히 덮어쓰지 않고 **예외**로 알린다
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from backend.services.output_paths import (
    _MAX_ATTEMPTS,
    reserve_unique_dir,
    reserve_unique_path,
)

# ── A·B·C — 이름 규칙 ──────────────────────────────────────────────────────

def test_충돌_없으면_요청한_이름_그대로(tmp_path):
    want = tmp_path / "sts_KJPDS02_20260807_094512.xlsx"
    got = reserve_unique_path(want)
    assert got == want, "충돌도 없는데 이름이 바뀌었다 — 사용자가 파일명으로 식별한다"
    assert got.exists()


def test_충돌하면_비켜가고_기존_파일을_안_건드린다(tmp_path):
    want = tmp_path / "uds_spec_20260807_094512.docx"
    first = reserve_unique_path(want)
    first.write_bytes(b"FIRST")

    second = reserve_unique_path(want)
    assert second != first
    assert second.name == "uds_spec_20260807_094512_2.docx"
    assert first.read_bytes() == b"FIRST", "앞선 산출물이 덮어써졌다"


def test_세_번째까지_순차로_비켜간다(tmp_path):
    want = tmp_path / "a.zip"
    names = [reserve_unique_path(want).name for _ in range(3)]
    assert names == ["a.zip", "a_2.zip", "a_3.zip"]


@pytest.mark.parametrize("suffix", [".xlsx", ".xlsm", ".docx", ".zip", ".json"])
def test_확장자를_보존한다(tmp_path, suffix):
    """`.xlsm` 이 `.xlsx` 가 되면 매크로 산출물이 아닌 다른 파일이 된다."""
    want = tmp_path / f"out{suffix}"
    reserve_unique_path(want)
    second = reserve_unique_path(want)
    assert second.suffix == suffix, f"확장자가 바뀌었다: {second.name}"
    assert second.stem.endswith("_2")


def test_점_여러개인_이름도_확장자만_바꾼다(tmp_path):
    want = tmp_path / "sts_v1.02_260420.xlsm"
    reserve_unique_path(want)
    second = reserve_unique_path(want)
    assert second.name == "sts_v1.02_260420_2.xlsm"


def test_없는_부모_디렉터리를_만든다(tmp_path):
    want = tmp_path / "a" / "b" / "out.xlsx"
    got = reserve_unique_path(want)
    assert got.exists() and got.parent.is_dir()


# ── D — 원자성(동시 요청) ──────────────────────────────────────────────────

def test_동시_요청이_같은_경로를_받지_않는다(tmp_path):
    """`exists()` 확인 후 쓰기 방식이면 여기서 같은 경로가 두 번 나온다(TOCTOU)."""
    want = tmp_path / "sts_same_second.xlsx"
    N = 12
    got: list[Path] = []
    lock = threading.Lock()
    start = threading.Barrier(N)

    def worker():
        start.wait(timeout=10)
        p = reserve_unique_path(want)
        with lock:
            got.append(p)

    threads = [threading.Thread(target=worker) for _ in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert not [t for t in threads if t.is_alive()], "스레드가 안 끝났다"

    assert len(got) == N
    assert len(set(got)) == N, f"동시 요청이 같은 경로를 받았다: {sorted(p.name for p in got)}"


def test_동시_쓰기가_서로를_덮어쓰지_않는다(tmp_path):
    """선점만으로 끝이 아니라 **각자 자기 파일에 쓴다**는 게 목적이다."""
    want = tmp_path / "report.docx"
    N = 8
    start = threading.Barrier(N)

    def worker(i):
        start.wait(timeout=10)
        reserve_unique_path(want).write_bytes(f"payload-{i}".encode())

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)

    payloads = sorted(p.read_bytes() for p in tmp_path.glob("report*.docx"))
    assert len(payloads) == N
    assert len(set(payloads)) == N, f"산출물이 서로를 덮어썼다: {payloads}"


# ── E — 상한 초과는 조용히 넘기지 않는다 ───────────────────────────────────

def test_상한까지_점유되면_예외(tmp_path):
    want = tmp_path / "x.txt"
    for _ in range(_MAX_ATTEMPTS):
        reserve_unique_path(want)
    with pytest.raises(OSError, match="선점하지 못했다"):
        reserve_unique_path(want)


# ── 디렉터리 변형 ──────────────────────────────────────────────────────────

def test_디렉터리도_공유되지_않는다(tmp_path):
    """`mkdir(exist_ok=True)` 는 두 요청이 **같은 폴더를 공유**해 안의 파일이 덮어써진다."""
    want = tmp_path / "suts_vectorcast_20260807_094512"
    first = reserve_unique_dir(want)
    (first / "model.json").write_text("A", encoding="utf-8")

    second = reserve_unique_dir(want)
    assert second != first and second.name.endswith("_2")
    (second / "model.json").write_text("B", encoding="utf-8")
    assert (first / "model.json").read_text(encoding="utf-8") == "A", "앞 패키지가 덮어써졌다"


def test_디렉터리_동시_요청도_유일하다(tmp_path):
    want = tmp_path / "pkg"
    N = 8
    got: list[Path] = []
    lock = threading.Lock()
    start = threading.Barrier(N)

    def worker():
        start.wait(timeout=10)
        d = reserve_unique_dir(want)
        with lock:
            got.append(d)

    threads = [threading.Thread(target=worker) for _ in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert len(set(got)) == N, f"같은 폴더를 공유했다: {sorted(d.name for d in got)}"


def test_디렉터리_상한초과도_예외(tmp_path):
    want = tmp_path / "d"
    for _ in range(_MAX_ATTEMPTS):
        reserve_unique_dir(want)
    with pytest.raises(OSError, match="선점하지 못했다"):
        reserve_unique_dir(want)


# ── 호출부 배선 (새 산출물 지점이 선점을 빠뜨리면 걸린다) ──────────────────

def test_산출물_지점이_선점을_쓴다():
    """`out_dir / f"...{ts}..."` 를 그대로 쓰는 산출물 지점이 다시 생기면 여기서 잡힌다."""
    root = Path(__file__).resolve().parents[2]
    checks = [
        ("backend/routers/jenkins.py", "uds_template_"),
        ("backend/routers/jenkins.py", "uds_spec_"),
        ("backend/routers/jenkins.py", "jenkins_reports_"),
        ("backend/routers/local.py", "suts_vectorcast_"),
    ]
    offenders = []
    for rel, token in checks:
        src = (root / rel).read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            s = line.strip()
            if token not in s or not s.startswith(("out_path =", "out_dir =")):
                continue
            if "reserve_unique_" not in s:
                offenders.append(f"{rel}:{i} {s[:70]}")
    assert offenders == [], f"산출물 경로가 선점 없이 조립된다: {offenders}"
