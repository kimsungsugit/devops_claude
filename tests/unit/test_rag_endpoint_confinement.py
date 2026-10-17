"""`/api/local/rag/*` 경로 봉인 (2026-10-02).

R53 리뷰가 범위 밖으로 남긴 것을 실제 요청으로 확인하고 막는다:
* 다섯 엔드포인트(status · ingest · ingest-files · use-pgvector · query)가 `repo_root / report_dir` 를 그대로 `mkdir` 했다 —
  절대경로나 ``..`` 이면 저장소 밖에 폴더 · KB 를 만들었다. 이제 보고서 폴더(`DEFAULT_REPORT_DIR`) 안만, 밖이면 403(경로를
  되비추지 않음),
* `rag/ingest` 는 요청 `config` 의 `vc_reports_paths` · `uds_spec_paths` · `req_docs_paths` · `codebase_paths` 로 **서버의 임의 경로**
  를 읽어 KB 에 넣었다(그 뒤 `rag/query` 가 내용을 돌려주고 임베딩 API 가 받는다). 이제 관리자만, 경로는 다른 `/api/local/*` 와
  같은 신뢰 루트로 봉인,
* `rag/use-pgvector` 는 로그인한 누구나 백엔드 전체의 KB 저장소 · DSN 을 바꿨다. 이제 관리자만, 거부되는 요청은 아무것도
  바꾸지 않는다(경로 검사가 전역 전환보다 먼저).
"""
from __future__ import annotations

from pathlib import Path

import pytest

import config

ADMIN = {"X-User": "tester"}                  # conftest registers `tester` as admin
NOBODY = {"X-User": "nobody_not_admin_zzz"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from backend.main import app
    base = tmp_path / "reports"
    base.mkdir()
    monkeypatch.setattr(config, "DEFAULT_REPORT_DIR", str(base))
    monkeypatch.setattr(config, "KB_GLOBAL_DIR", "", raising=False)
    monkeypatch.setattr(config, "KB_SOURCES_DIR", "", raising=False)
    monkeypatch.setattr(config, "KB_STORAGE", "sqlite", raising=False)
    monkeypatch.setattr(config, "FORCE_PGVECTOR", False, raising=False)
    return TestClient(app, raise_server_exceptions=False), tmp_path


ESCAPES = ("../outside_kb", None)          # None: an absolute path outside (filled per test)


@pytest.mark.parametrize("escape", ESCAPES)
def test_every_rag_endpoint_keeps_the_kb_folder_under_reports(client, escape):
    c, tmp = client
    target = escape or str(tmp / "abs_outside_kb")
    outside = (tmp / "reports" / escape).resolve() if escape else Path(target)
    calls = [("/api/local/rag/status", {"json": {"report_dir": target}}, NOBODY),
             ("/api/local/rag/ingest", {"json": {"report_dir": target, "config": {}}}, ADMIN),
             ("/api/local/rag/ingest-files", {"data": {"report_dir": target}}, NOBODY),
             ("/api/local/rag/use-pgvector", {"json": {"report_dir": target, "pgvector_dsn": "postgresql://x"}}, ADMIN),
             ("/api/local/rag/query", {"json": {"report_dir": target, "query": "q"}}, NOBODY),
             ("/api/local/rag/status", {"json": {"config": {"report_dir": target}}}, NOBODY)]     # JSON nested too
    for url, kw, who in calls:
        res = c.post(url, headers=who, **kw)
        assert res.status_code == 403, (url, res.status_code, res.text[:200])
        assert str(tmp) not in res.text                             # the refusal echoes no path
    assert not outside.exists(), "a refused request created the folder"


def test_a_refused_pgvector_switch_changes_nothing(client):
    c, tmp = client
    res = c.post("/api/local/rag/use-pgvector", headers=ADMIN,
                 json={"report_dir": str(tmp / "elsewhere"), "pgvector_dsn": "postgresql://x"})
    assert res.status_code == 403
    assert config.FORCE_PGVECTOR is False and str(config.KB_STORAGE) == "sqlite"


@pytest.mark.parametrize("url,body", [
    ("/api/local/rag/ingest", {"config": {}}),
    ("/api/local/rag/use-pgvector", {"pgvector_dsn": "postgresql://x"}),
])
def test_the_operator_endpoints_need_an_admin(client, url, body):
    c, _tmp = client
    res = c.post(url, headers=NOBODY, json=body)
    assert res.status_code in (401, 403), (url, res.status_code)
    assert config.FORCE_PGVECTOR is False


def test_the_ingest_reads_no_server_path_outside_the_trusted_roots(client):
    c, _tmp = client
    outside = str(Path.home().parent)                 # e.g. C:/Users — no trusted root
    for key in ("vc_reports_paths", "uds_spec_paths", "req_docs_paths", "codebase_paths"):
        res = c.post("/api/local/rag/ingest", headers=ADMIN, json={"config": {key: outside}})
        assert res.status_code == 403, (key, res.status_code)
        assert outside not in res.text


def test_the_default_folder_still_works(client):
    """대조군 — the web's call (`rag/status` with no body field) still answers."""
    c, tmp = client
    res = c.post("/api/local/rag/status", headers=NOBODY, json={})
    assert res.status_code == 200, res.text[:300]
    assert (tmp / "reports").exists()


@pytest.fixture
def no_unc_resolve(monkeypatch):
    """Fails the test if `Path.resolve` is ever given a UNC path — resolving one opens an SMB connection first."""
    import pathlib
    real = pathlib.Path.resolve

    def guard(self, *a, **k):
        assert not str(self).startswith(("\\\\", "//")), "resolve() touched a UNC path"
        return real(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "resolve", guard)


UNCS = ["\\\\192.0.2.1\\share\\kb", "//192.0.2.1/share/kb"]


@pytest.mark.parametrize("unc", UNCS)
def test_a_unc_report_dir_is_refused_before_it_is_touched(client, no_unc_resolve, unc):
    """(review W1) the 403 came after `resolve()` had already opened an SMB connection (NTLM hash offered)."""
    c, _tmp = client
    for url, kw in (("/api/local/rag/status", {"json": {"report_dir": unc}}),
                    ("/api/local/rag/query", {"json": {"report_dir": unc, "query": "q"}}),
                    ("/api/local/rag/ingest-files", {"data": {"report_dir": unc}})):
        assert c.post(url, headers=NOBODY, **kw).status_code == 403, url


@pytest.mark.parametrize("unc", UNCS)
def test_confine_refuses_a_unc_path_before_it_is_touched(no_unc_resolve, unc):
    """The same in the helper twenty `/api/local/*` paths use."""
    from fastapi import HTTPException

    from backend.services.paths import confine
    with pytest.raises(HTTPException) as err:
        confine(unc)
    assert err.value.status_code == 403


def test_nested_report_dirs_and_every_path_list_form_are_confined(client):
    """(review I7) the JSON-nested `config.report_dir` of query and ingest; the ingest's path keys as a list, with
    ``;`` and with a newline."""
    c, tmp = client
    outside = str(tmp / "nested_outside")
    for url, body, who in (("/api/local/rag/query", {"query": "q", "config": {"report_dir": outside}}, NOBODY),
                           ("/api/local/rag/ingest", {"config": {"report_dir": outside}}, ADMIN)):
        assert c.post(url, headers=who, json=body).status_code == 403, url
    out = str(Path.home().parent)
    for value in ([str(tmp), out], f"{tmp};{out}", f"{tmp}\n{out}"):
        res = c.post("/api/local/rag/ingest", headers=ADMIN, json={"config": {"codebase_paths": value}})
        assert res.status_code == 403, value

