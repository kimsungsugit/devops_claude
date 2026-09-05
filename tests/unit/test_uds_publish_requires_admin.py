"""`/api/jenkins/uds/publish` 는 admin 전용이고, 저장소 `docs/` 밖에는 쓰지 않는다.

(2026-09-03 R27 B-8, 계획서 §8 #7 · 리뷰 C1)

이 엔드포인트는 산출물을 **저장소 안에 쓴다**. 그런데 `jenkins.py` 의 라우터는 `APIRouter()`
라 라우터 레벨 의존성이 없고, 핸들러에도 `require_*` 가 0 이라 **로그인만으로** 게시가 됐다 —
빌더(evidence 생성)는 전부 `require_admin` 인데 그 산출물을 게시하는 자리만 열려 있었다.
게다가 `target_dir` 이 봉인되지 않아 `../../X` · `D:/X` 로 저장소 밖 디렉터리를 만들고 썼다.

- 구조: 데코레이터에 `dependencies=[Depends(require_admin)]` 가 실제로 붙어 있다.
- 행동: admin 이 아닌 사용자는 403 · admin 은 게이트를 지나 파일 검증(404)까지 간다.
- 봉인: `target_dir` 이 `docs/` 밖이면 파일 조회 **전에** 403 이다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from tests.unit._source_probe import source_of

client = TestClient(app)
# 임시 파일 fixture 가 실제 파일을 만든다 — `tmp_path` 는 pytest 가 준다.


def test_publish_route_declares_require_admin_and_confines_target_dir() -> None:
    from backend.routers import jenkins as J
    src = source_of(J.jenkins_uds_publish)     # 데코레이터를 **포함**한 정본 텍스트
    assert '@router.post("/api/jenkins/uds/publish", dependencies=[Depends(require_admin)])' in src, (
        "publish 가 다시 로그인만으로 열렸다")
    assert "is_under_any(docs_dir, [docs_root])" in src, "target_dir 봉인이 사라졌다"
    assert "os.replace(" in src, "원자적 교체가 사라졌다 — 동시 게시가 문서를 찢는다"
    assert "tempfile.mkstemp(" in src, "임시 이름이 결정적이면 경합이 tmp 로 옮겨가고 2회차 replace 가 500 이다"


def test_publish_writes_atomically_and_leaves_no_temp_residue(tmp_path, monkeypatch) -> None:
    """같은 이름을 두 번 게시해도 `.publishing` 잔여물 0 · 최종 내용은 마지막 게시분.

    저장소 `docs/` 에 실제로 쓰지 않도록 `repo_root` 를 tmp 로 돌린다.
    """
    from backend.routers import jenkins as J
    fake_repo = tmp_path / "repo"
    (fake_repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(J, "repo_root", fake_repo)
    cache_root = tmp_path / "cache"
    exports = cache_root / "exports"
    exports.mkdir(parents=True)
    src = exports / "UDS_r27.docx"
    for payload in (b"first", b"second"):
        src.write_bytes(payload)
        r = client.post("/api/jenkins/uds/publish", headers={"X-User": "tester"},
                        json={"job_url": "http://j/job/x/", "cache_root": str(cache_root),
                              "filename": "UDS_r27.docx", "target_dir": "docs/r27"})
        assert r.status_code == 200, r.text
    out_dir = fake_repo / "docs" / "r27"
    assert (out_dir / "UDS_r27.docx").read_bytes() == b"second"
    assert not list(out_dir.glob("*.publishing")), "임시 파일 잔여물이 남았다"


def test_non_admin_cannot_publish() -> None:
    # 회귀 기본 admin 은 `tester`/`hbrnd2` (tests/conftest.py). `nobody` 는 admin 이 아니다.
    r = client.post("/api/jenkins/uds/publish", headers={"X-User": "nobody"},
                    json={"job_url": "http://j/job/x/", "filename": "x.docx"})
    assert r.status_code == 403, r.text


def test_admin_passes_the_gate_and_reaches_file_validation() -> None:
    r = client.post("/api/jenkins/uds/publish", headers={"X-User": "tester"},
                    json={"job_url": "http://j/job/x/", "filename": "__no_such_file__.docx"})
    # 게이트는 지났고 파일이 없어 404 — 200 이면 없는 파일을 게시한 것이고 403 이면 admin 이 막힌 것.
    assert r.status_code == 404, r.text


@pytest.mark.parametrize("target_dir", ["../../ESCAPED", "D:/ESCAPED_ABS", "docs/../../..", "..", "/"])
def test_target_dir_outside_docs_is_refused_before_any_io(target_dir: str) -> None:
    """저장소 밖(또는 `docs/` 밖)은 403 — 파일이 있든 없든, 디렉터리를 만들기 전에."""
    r = client.post("/api/jenkins/uds/publish", headers={"X-User": "tester"},
                    json={"job_url": "http://j/job/x/", "filename": "__no_such_file__.docx",
                          "target_dir": target_dir})
    assert r.status_code == 403, (target_dir, r.text)
    assert "docs/" in str(r.json())


@pytest.mark.parametrize("target_dir", ["docs", "docs/uds", "docs/../docs/x"])
def test_target_dir_under_docs_is_allowed(target_dir: str) -> None:
    """`docs/` 아래는 통과해 파일 검증(404)까지 간다 — 봉인이 정상 경로까지 막지 않는다."""
    r = client.post("/api/jenkins/uds/publish", headers={"X-User": "tester"},
                    json={"job_url": "http://j/job/x/", "filename": "__no_such_file__.docx",
                          "target_dir": target_dir})
    assert r.status_code == 404, (target_dir, r.text)
