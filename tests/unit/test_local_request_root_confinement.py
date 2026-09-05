"""요청자가 지정한 base(`project_root`)를 확정한다 — /api/local/* 보안 표면.

## 실측한 것 (2026-08-04, 전부 라이브 요청으로 재현)

`backend/routers/local.py` 의 endpoint **20곳**이 `req.project_root` 를 **그대로 base 로**
썼다. 인증만 통과하면(당시엔 `X-User` 헤더 한 줄) 디스크 임의 위치를 읽고 쓸 수 있었다:

    editor/write  project_root="C:/Users/<me>"                   -> 200, 홈에 파일 생성
    editor/write  project_root=…\\Start Menu\\Programs\\Startup  -> 200, **로그인 시 자동실행**
    editor/write  rel_path="backend/routers/__probe.py"          -> 200, **코드 주입 표면**
    editor/read   rel_path=".env"                                -> 200, 2,165B (JWT_SECRET 포함)
    editor/read   rel_path="reports/quality.sqlite"              -> 200, 'SQLite format 3\\x00'

⚠ **traversal 가드는 이미 있었고 정상 동작했다** — `../` 3종 전부 500·미생성. 결함은
   traversal 이 아니라 **base 지정**이었다. `rel_path` 만 검사하고 root 는 body 를 믿었다.

⚠ 같은 파일의 `open-file`/`read-abs`/`open-folder` 는 **이미** 이 확정을 하고 있었다.
   읽기전용 3곳은 잠겼고 쓰기 3곳은 열려 있던 비대칭이다.

## 왜 확정만으로는 부족한가

`.env`·`reports/quality.sqlite` 는 `repo_root` **밑**이라 화이트리스트를 통과한다.
그래서 민감 경로 거부를 함께 둔다. 그리고 반증이 짚은 대로 **editor 만 잠그면 구멍이
옮겨간다** — `/api/local/search` 가 임의 base 밑을 grep 해 `.env` 값을 그대로 돌려주는 것을
재현했다. 그래서 20곳을 한 번에 간다(사용자 결정: "20곳 전부 잠금").

## 정당한 사용자

HTTP 호출자 **0건**(771커밋). 프론트가 부르는 `/api/local/*` 는
impact/trigger · project-setup/* · rag/status · sits/export-vectorcast · vectorcast/* 뿐이고
이 20곳은 하나도 없다. MCP 의 `write_file`/`replace_in_file` 은 HTTP 를 안 타고
`local_service` 를 in-process 로 부르므로 **무영향**(자체 가드 있음).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

REPO_ROOT = Path(__file__).resolve().parents[2]

# 잠근 20곳 — 이 목록이 곧 계약이다.
LOCKED_PATHS = [
    "/api/local/scm",
    "/api/local/kb/list", "/api/local/kb/delete",
    "/api/local/editor/read", "/api/local/editor/write", "/api/local/editor/replace",
    "/api/local/editor/read-abs", "/api/local/preflight",
    "/api/local/list-dir", "/api/local/search", "/api/local/replace-text",
    "/api/local/git/status", "/api/local/git/diff", "/api/local/git/log",
    "/api/local/git/branches", "/api/local/git/checkout", "/api/local/git/create-branch",
    "/api/local/git/stage", "/api/local/git/unstage", "/api/local/git/commit",
]


@pytest.fixture
def confine():
    from backend.routers.local import confine_request_root

    return confine_request_root


class TestBaseIsConfined:
    def test_repo_root_is_allowed(self, confine):
        assert Path(confine(str(REPO_ROOT))).resolve() == REPO_ROOT.resolve()

    def test_empty_falls_back_to_repo_root(self, confine):
        assert Path(confine("")).resolve() == REPO_ROOT.resolve()
        assert Path(confine(None)).resolve() == REPO_ROOT.resolve()

    @pytest.mark.parametrize(
        "outside",
        [
            "C:/Users",
            "C:/Windows/Temp",
            "/nonexistent/root",
            "/tmp",
        ],
    )
    def test_outside_is_403(self, confine, outside):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            confine(outside)
        assert exc.value.status_code == 403

    def test_traversal_via_base_is_403(self, confine):
        """base 에 `..` 를 넣어 빠져나가는 것도 막힌다(resolve 후 검사)."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            confine(str(REPO_ROOT / ".." / ".."))
        assert exc.value.status_code == 403

    def test_error_does_not_disclose_allowed_roots(self, confine):
        """실패 응답이 허용 경로를 알려 주면 그 자체가 정찰 정보다."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            confine("C:/Windows")
        detail = str(exc.value.detail)
        assert "devops_pro_cache" not in detail
        assert str(REPO_ROOT) not in detail


class TestSensitiveFilesAreDeniedEvenInsideRepo:
    """확정을 통과해도 내주면 안 되는 것 — 전부 `repo_root` 밑이라 화이트리스트로는 안 걸린다."""

    @pytest.mark.parametrize(
        "rel",
        [
            ".env",
            ".env.example",
            "reports/quality.sqlite",
            "reports/quality.sqlite.bak",   # 접미가 더 붙어도
            "config/admin_users.json",
            "config/users.json",
            "config/allowed_users.json",
        ],
    )
    def test_denied(self, confine, rel):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            confine(str(REPO_ROOT), rel_path=rel)
        assert exc.value.status_code == 403

    @pytest.mark.parametrize("rel", ["README.md", "docs/plans", "backend/routers/local.py"])
    def test_ordinary_repo_files_still_pass(self, confine, rel):
        """대조군 — 전부 막아 버리면 기능이 죽은 것이지 고친 게 아니다."""
        assert confine(str(REPO_ROOT), rel_path=rel)


class TestEveryLockedEndpointIsWired:
    """20곳 **전부**가 admin 게이트 + base 확정을 거치는지 소스에서 확인한다.

    ⚠ 한 곳만 빠뜨리면 그 입구로 그대로 들어간다 — 이 저장소가 반복해 겪은
      "판정 복제, 한쪽만 고침" 이고, 이번 표면이 정확히 그 모양이었다
      (읽기전용 3곳은 잠겨 있었고 쓰기 3곳만 열려 있었다).
    """

    @pytest.fixture(scope="class")
    def source(self):
        return (REPO_ROOT / "backend" / "routers" / "local.py").read_text(encoding="utf-8")

    @pytest.mark.parametrize("path", LOCKED_PATHS)
    def test_has_admin_dependency(self, source, path):
        needle = f'@router.post("{path}", dependencies=[Depends(require_admin)])'
        assert needle in source, f"{path} 에 admin 게이트가 없다"

    def test_no_raw_project_root_use_remains(self, source):
        """`req.project_root` 를 확정 없이 그대로 넘기는 곳이 남으면 안 된다."""
        offenders = [
            ln.strip() for ln in source.splitlines()
            if "req.project_root" in ln
            and "confine_request_root" not in ln
            and not ln.lstrip().startswith("#")
        ]
        assert not offenders, f"확정을 안 거치는 사용처가 남아 있다: {offenders}"

    def test_confinement_helper_checks_allowed_roots(self, source):
        tree = ast.parse(source)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "confine_request_root"
        )
        called = {
            (c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", ""))
            for c in ast.walk(fn) if isinstance(c, ast.Call)
        }
        assert "is_under_any" in called, "허용 루트 검사를 안 한다"
        assert "_deny_sensitive_target" in called, "민감 경로 거부를 안 한다"


class TestLiveEndpointsReject:
    """실제 요청으로 — 소스 검사만 두면 배선이 끊겨도 초록이다."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from backend.main import app

        return TestClient(app, raise_server_exceptions=False)

    # conftest 가 `tester`/`hbrnd2` 를 admin 으로 등록한다.
    ADMIN = {"X-User": "tester"}

    def test_admin_cannot_write_outside_repo(self, client):
        res = client.post(
            "/api/local/editor/write",
            json={"project_root": "C:/Users", "rel_path": "__probe.tmp", "content": "x"},
            headers=self.ADMIN,
        )
        assert res.status_code == 403

    def test_admin_cannot_read_dotenv(self, client):
        res = client.post(
            "/api/local/editor/read",
            json={"project_root": str(REPO_ROOT), "rel_path": ".env"},
            headers=self.ADMIN,
        )
        assert res.status_code == 403

    def test_admin_cannot_read_quality_db(self, client):
        res = client.post(
            "/api/local/editor/read",
            json={"project_root": str(REPO_ROOT), "rel_path": "reports/quality.sqlite"},
            headers=self.ADMIN,
        )
        assert res.status_code == 403

    def test_search_cannot_walk_outside_repo(self, client):
        """`editor` 만 잠그면 구멍이 여기로 옮겨간다 — 반증이 재현한 경로."""
        res = client.post(
            "/api/local/search",
            json={"project_root": "C:/Users", "rel_path": ".", "query": "SECRET"},
            headers=self.ADMIN,
        )
        assert res.status_code == 403

    def test_non_admin_is_rejected(self, client):
        res = client.post(
            "/api/local/editor/write",
            json={"project_root": str(REPO_ROOT), "rel_path": "__probe.tmp", "content": "x"},
            headers={"X-User": "nobody_not_admin_zzz"},
        )
        assert res.status_code in (401, 403), "비관리자가 쓰기에 도달했다"

    def test_legitimate_in_repo_write_still_works(self, client, tmp_path):
        """대조군 — 막기만 하고 기능이 죽으면 고친 게 아니다."""
        workdir = REPO_ROOT / ".codex_tmp"
        workdir.mkdir(parents=True, exist_ok=True)
        probe = workdir / "__confine_probe.tmp"
        try:
            res = client.post(
                "/api/local/editor/write",
                json={
                    "project_root": str(REPO_ROOT),
                    "rel_path": f".codex_tmp/{probe.name}",
                    "content": "ok",
                },
                headers=self.ADMIN,
            )
            assert res.status_code == 200, res.text
            assert probe.exists()
        finally:
            probe.unlink(missing_ok=True)
