# -*- coding: utf-8 -*-
"""VectorCAST 패키지 endpoint 3종 — 목록/다운로드/삭제.

## 왜 필요한가

이 세 endpoint 에 테스트가 **0건**이었고, 그 사이 세 가지가 동시에 고장 나 있었다
(실측 2026-08-07, 재기동 직후 로그에서 발견):

  1. **목록이 등록 경로의 한쪽만 봤다.** 쓰기는 두 갈래인데
     (`/api/local/*/export-vectorcast` → `reports/vectorcast`,
      `/api/jenkins/suts/export-vectorcast` → `<cache_root>/exports/vectorcast`)
     읽기는 `report_dir` 하나뿐이었다. 게다가 프론트가 cache 경로를 `report_dir` 로
     보내 **403** 이 났고, 프론트는 그걸 `catch` 로 삼켜 화면엔
     "등록된 패키지가 없습니다" — **403 이 '없음'으로 위장**했다.
  2. **`delete` 에 경로 검사가 없었다.** 인증된 사용자면 `package_path` 로 서버의
     **아무 디렉터리나** `shutil.rmtree` 할 수 있었다. `download` 도 임의 파일을 줬다.
  3. `download` 는 `<a href download>` 라 `Authorization` 이 안 실려 401 이었다
     (프론트 쪽 가드는 `DocGenSection.test.jsx`).

## 고정하는 계약

  A. 목록은 **쓰는 쪽 루트를 전부** 훑는다 — 한쪽만 고르는 수정은 반대쪽을 지운다
  B. 못 훑은 루트·0건은 **사유와 위치를 밝힌다** (침묵 금지)
  C. 조회는 **부작용이 없다** — 없는 캐시 경로를 만들지 않는다
  D. 목록·다운로드·삭제는 **같은 루트 집합**을 쓴다. 삭제는 루트의 **직계 하위**만
     (단순 하위 검사는 `vectorcast` 디렉터리째 지운다)
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

import config
from backend.routers.local import (
    _confine_vcast_package,
    _vcast_roots,
    local_vectorcast_delete,
    local_vectorcast_download,
    local_vectorcast_list,
)


def _pkg(root: Path, name: str, *, files: tuple[str, ...] = ("a.tst",)) -> Path:
    """패키지 디렉터리 하나를 실제로 만든다 (경로 계약은 실물로만 검증된다)."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        (d / f).write_text("x", encoding="utf-8")
    return d


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """`reports/` 기준을 tmp 로 옮긴다 — 머신의 실제 reports 를 건드리지 않게."""
    reports = tmp_path / "reports"
    (reports / "vectorcast").mkdir(parents=True)
    monkeypatch.setattr(config, "DEFAULT_REPORT_DIR", str(reports))

    cache = tmp_path / "cache" / "alice"          # 사용자별 캐시
    (cache / "exports" / "vectorcast").mkdir(parents=True)

    return {
        "tmp": tmp_path,
        "reports_root": reports / "vectorcast",
        "cache_root": cache,
        "jenkins_root": cache / "exports" / "vectorcast",
        "legacy_root": tmp_path / "cache" / "exports" / "vectorcast",
    }


# ── A — 두 루트를 모두 훑는다 ──────────────────────────────────────────────

def test_목록이_로컬과_젠킨스_루트를_모두_훑는다(env):
    """⚠ 한쪽만 고르는 수정(a안/b안)은 어느 쪽을 골라도 반대쪽을 통째로 지운다."""
    _pkg(env["reports_root"], "suts_vectorcast_20260101_000000")
    _pkg(env["jenkins_root"], "suts_vectorcast_job_20260102_000000")

    out = local_vectorcast_list(report_dir="", cache_root=str(env["cache_root"]))

    names = {p["name"] for p in out["packages"]}
    assert names == {"suts_vectorcast_20260101_000000", "suts_vectorcast_job_20260102_000000"}
    assert {p["source"] for p in out["packages"]} == {"reports", "jenkins_cache"}


def test_legacy_공유_루트도_훑는다(env):
    """사용자 세그먼트가 붙기 전 등록물은 상위 공유 루트에 남는다(캐시 이중구조)."""
    env["legacy_root"].mkdir(parents=True)
    _pkg(env["legacy_root"], "suts_vectorcast_old")

    out = local_vectorcast_list(report_dir="", cache_root=str(env["cache_root"]))

    found = [p for p in out["packages"] if p["name"] == "suts_vectorcast_old"]
    assert found, "공유 캐시의 등록물이 안 보인다"
    assert found[0]["source"] == "jenkins_cache_legacy"


def test_legacy_루트가_없으면_지어내지_않는다(env):
    """⚠ 없는 루트를 목록에 올리면 '조회한 위치'가 거짓이 되고 진단이 흐려진다."""
    roots, _ = _vcast_roots("", str(env["cache_root"]))
    assert "jenkins_cache_legacy" not in {s for s, _ in roots}


def test_같은_루트를_두번_세지_않는다(tmp_path, monkeypatch):
    """⚠ 겹침을 **실제로 만들어** 검증한다.

    처음엔 기본 픽스처(두 루트가 자연히 다름)로 `len(set(...))` 만 봤는데, 그러면
    dedupe 를 통째로 지워도 통과한다 — 충돌이 없는 입력으로 dedupe 를 시험한 셈이다.
    `reports/` 를 `<cache_root>/exports` 에 겹쳐 두 루트가 같은 디렉터리가 되게 한다.
    """
    cache = tmp_path / "cache"
    collide = cache / "exports"                 # jenkins 루트가 여기 / "vectorcast"
    (collide / "vectorcast").mkdir(parents=True)
    monkeypatch.setattr(config, "DEFAULT_REPORT_DIR", str(collide))
    _pkg(collide / "vectorcast", "dup_pkg")

    roots, _ = _vcast_roots("", str(cache))
    paths = [r for _, r in roots]
    assert len(paths) == len(set(paths)), f"같은 디렉터리를 두 루트로 셌다: {paths}"

    out = local_vectorcast_list(report_dir="", cache_root=str(cache))
    assert [p["name"] for p in out["packages"]] == ["dup_pkg"], "패키지가 두 번 나왔다"


# ── B — 침묵 금지 ─────────────────────────────────────────────────────────

def test_허용밖_report_dir_은_전체를_실패시키지_않고_사유를_남긴다(env):
    """구 프론트가 cache 경로를 report_dir 로 보내던 전례 — 그때 403 이 전부를 죽였다."""
    _pkg(env["reports_root"], "still_visible")

    out = local_vectorcast_list(report_dir=str(env["tmp"] / "elsewhere"),
                                cache_root=str(env["cache_root"]))

    assert any("report_dir" in w for w in out["warnings"]), "무시했다는 사실을 안 알린다"
    assert [p["name"] for p in out["packages"]] == ["still_visible"], \
        "report_dir 하나 때문에 기본 루트 결과까지 잃었다"


def test_0건일때_어느_위치를_봤는지_밝힌다(env):
    """0건이 '미등록'인지 '경로 오설정'인지 화면이 구분할 수 있어야 한다."""
    out = local_vectorcast_list(report_dir="", cache_root=str(env["cache_root"]))

    assert out["packages"] == []
    scanned = {s["source"]: s for s in out["scanned_roots"]}
    assert set(scanned) == {"reports", "jenkins_cache"}
    assert all("path" in s and "exists" in s for s in scanned.values())


def test_읽을수_없는_루트는_사유가_올라온다(env, monkeypatch):
    """루트가 있는데 못 읽는 것과 없는 것은 다른 사건이다."""
    _pkg(env["reports_root"], "x")
    real_iterdir = Path.iterdir

    def boom(self):
        if self == env["reports_root"]:
            raise PermissionError("접근 거부")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    out = local_vectorcast_list(report_dir="", cache_root=str(env["cache_root"]))

    assert any("PermissionError" in w for w in out["warnings"])
    assert any(s["error"] for s in out["scanned_roots"] if s["source"] == "reports")


# ── C — 조회는 부작용이 없다 ──────────────────────────────────────────────

def test_목록_조회가_없는_캐시_디렉터리를_만들지_않는다(env):
    """⚠ 만들어 버리면 오타 난 경로도 실재하게 돼 '왜 비었나' 진단이 뒤집힌다."""
    ghost = env["tmp"] / "does_not_exist" / "bob"
    assert not ghost.exists()

    local_vectorcast_list(report_dir="", cache_root=str(ghost))

    assert not ghost.exists(), "조회가 캐시 디렉터리를 생성했다"


# ── D — 목록·삭제·다운로드가 같은 루트 집합을 쓴다 ───────────────────────

def test_정상_패키지는_통과한다(env):
    d = _pkg(env["reports_root"], "ok_pkg")
    assert _confine_vcast_package(str(d), "", str(env["cache_root"])) == d.resolve()


def test_젠킨스_루트_패키지도_통과한다(env):
    """목록에 뜨는데 못 지우면 안 된다 — 두 판정이 같은 출처여야 하는 이유."""
    d = _pkg(env["jenkins_root"], "jenkins_pkg")
    assert _confine_vcast_package(str(d), "", str(env["cache_root"])) == d.resolve()


@pytest.mark.parametrize("label", ["루트 자기 자신", "상위 traversal", "무관한 경로"])
def test_허용밖_경로는_403(env, label):
    _pkg(env["reports_root"], "p")
    target = {
        "루트 자기 자신": env["reports_root"],           # ⚠ vectorcast 디렉터리째 삭제 방지
        "상위 traversal": env["reports_root"] / "p" / ".." / ".." / "..",
        "무관한 경로": env["tmp"] / "secret",
    }[label]
    with pytest.raises(HTTPException) as exc:
        _confine_vcast_package(str(target), "", str(env["cache_root"]))
    assert exc.value.status_code == 403


def test_빈_package_path_는_400(env):
    with pytest.raises(HTTPException) as exc:
        _confine_vcast_package("", "", str(env["cache_root"]))
    assert exc.value.status_code == 400


def test_삭제가_허용밖_디렉터리를_실제로_지우지_않는다(env):
    """⚠ 관측량은 '예외'가 아니라 **파일이 남아 있는가** 다.

    confine 호출만 단언하면 `rmtree` 를 먼저 부르도록 순서를 바꾼 뮤테이션이 생존한다.
    """
    victim = env["tmp"] / "important"
    victim.mkdir()
    (victim / "data.txt").write_text("소중함", encoding="utf-8")

    with pytest.raises(HTTPException):
        local_vectorcast_delete(package_path=str(victim), cache_root=str(env["cache_root"]))

    assert (victim / "data.txt").read_text(encoding="utf-8") == "소중함", "허용 밖인데 지워졌다"


def test_삭제가_루트_자체를_지우지_않는다(env):
    """단순 '하위인가' 검사는 루트 자신을 통과시킨다 — 전 패키지가 한 번에 날아간다."""
    _pkg(env["reports_root"], "keep_me")

    with pytest.raises(HTTPException):
        local_vectorcast_delete(package_path=str(env["reports_root"]),
                                cache_root=str(env["cache_root"]))

    assert (env["reports_root"] / "keep_me").is_dir(), "vectorcast 루트가 통째로 지워졌다"


def test_정상_삭제는_동작한다(env):
    """차단만 하고 본 기능이 죽으면 그것도 결함이다."""
    d = _pkg(env["reports_root"], "bye_pkg")
    out = local_vectorcast_delete(package_path=str(d), cache_root=str(env["cache_root"]))
    assert out["ok"] is True and not d.exists()


@pytest.mark.parametrize("kind", ["낱개 파일", "존재하지 않음"])
def test_패키지가_아닌_대상은_404지_500이_아니다(env, kind):
    """⚠ confine 은 **위치**만 본다 — 종류는 안 본다.

    `reports/vectorcast/` 엔 낱개 `.json`/`.md` 가 실제로 섞여 있다(실측). 그 경로는
    부모가 루트라 confine 을 통과하고, 곧바로 `shutil.rmtree` 에서 `NotADirectoryError`
    로 터져 **500** 이 된다. 클라이언트에겐 "서버 오류"로 보이지만 실제로는 잘못된 요청이다.
    """
    if kind == "낱개 파일":
        target = env["reports_root"] / "loose.json"
        target.write_text("{}", encoding="utf-8")
    else:
        target = env["reports_root"] / "gone_pkg"

    with pytest.raises(HTTPException) as exc:
        local_vectorcast_delete(package_path=str(target), cache_root=str(env["cache_root"]))
    assert exc.value.status_code == 404

    if kind == "낱개 파일":
        assert target.exists(), "패키지가 아닌데 지워졌다"


@pytest.mark.parametrize("kind", ["낱개 파일", "존재하지 않음"])
def test_다운로드도_패키지가_아니면_404(env, kind):
    target = env["reports_root"] / ("loose2.json" if kind == "낱개 파일" else "gone_pkg")
    if kind == "낱개 파일":
        target.write_text("{}", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        local_vectorcast_download(package_path=str(target), cache_root=str(env["cache_root"]))
    assert exc.value.status_code == 404


def test_다운로드_filename_이_패키지를_벗어나지_못한다(env):
    """`pkg_dir / filename` 만으론 `../` 로 밖을 짚는다."""
    d = _pkg(env["reports_root"], "dl_pkg")
    secret = env["reports_root"] / "other_secret.txt"
    secret.write_text("비밀", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        local_vectorcast_download(package_path=str(d), filename="../other_secret.txt",
                                  cache_root=str(env["cache_root"]))
    assert exc.value.status_code in (400, 404)
    assert secret.read_text(encoding="utf-8") == "비밀"


def test_다운로드가_허용밖_패키지를_거부한다(env):
    outside = env["tmp"] / "outside_pkg"
    outside.mkdir()
    (outside / "f.txt").write_text("x", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        local_vectorcast_download(package_path=str(outside), cache_root=str(env["cache_root"]))
    assert exc.value.status_code == 403


def test_다운로드_정상_파일은_반환된다(env):
    d = _pkg(env["reports_root"], "dl_ok", files=("report.tst",))
    resp = local_vectorcast_download(package_path=str(d), filename="report.tst",
                                     cache_root=str(env["cache_root"]))
    assert Path(resp.path).name == "report.tst"


# ── 목록 내용 계약 ────────────────────────────────────────────────────────

def test_manifest_가_깨져도_목록은_뜬다(env):
    """summary 하나 때문에 패키지 전체가 사라지면 안 된다."""
    d = _pkg(env["reports_root"], "broken_manifest")
    (d / "manifest.json").write_text("{ not json", encoding="utf-8")

    out = local_vectorcast_list(report_dir="", cache_root=str(env["cache_root"]))
    row = next(p for p in out["packages"] if p["name"] == "broken_manifest")
    assert row["summary"] == {}


def test_doc_type_과_summary_가_실린다(env):
    d = _pkg(env["reports_root"], "sits_vectorcast_20260101")
    (d / "manifest.json").write_text('{"summary": {"unit_count": 7}}', encoding="utf-8")

    out = local_vectorcast_list(report_dir="", cache_root=str(env["cache_root"]))
    row = next(p for p in out["packages"] if p["name"].startswith("sits_"))
    assert row["doc_type"] == "sits" and row["summary"]["unit_count"] == 7


def test_파일만_있는_항목은_패키지가_아니다(env):
    """`reports/vectorcast` 에는 낱개 .json/.md 도 섞여 있다(실측)."""
    (env["reports_root"] / "loose.json").write_text("{}", encoding="utf-8")
    out = local_vectorcast_list(report_dir="", cache_root=str(env["cache_root"]))
    assert out["packages"] == []
