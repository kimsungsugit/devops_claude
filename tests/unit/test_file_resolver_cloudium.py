"""Tests for CloudiumFileResolver gate process & read-only behavior."""
from __future__ import annotations

import base64
import json
import logging
import socket
import threading

import pytest

from backend.services import file_resolver
from backend.services.file_resolver import (
    CloudiumFileResolver,
    DEFAULT_GATE_PROCESS,
    LocalFileResolver,
    is_gate_running,
)


@pytest.fixture(autouse=True)
def _reset_resolver_and_gate_cache(monkeypatch, tmp_path):
    """Ensure each test starts with a clean LOCAL resolver and gate cache.

    이전엔 캐시만 reset했지만 일부 테스트가 set_resolver(...) finally를 빠뜨리면
    다음 테스트로 누설됨. autouse로 두 가지 모두 reset해 누설 차단.

    추가: workspace bypass 회귀 차단 — pytest tmp_path가 workspace 안 .codex_tmp/에
    생성되어 자동 통과되는 케이스 회피. 테스트용으로 _PROJECT_ROOT를 isolate된
    fake로 가짜 변경. workspace bypass 자체 검증은 개별 테스트에서 monkeypatch
    원복.
    """
    file_resolver.invalidate_gate_cache()
    file_resolver.set_resolver(file_resolver.LocalFileResolver())
    monkeypatch.setattr(file_resolver, "_PROJECT_ROOT", tmp_path / "_isolated_fake_root")
    yield
    file_resolver.invalidate_gate_cache()
    file_resolver.set_resolver(file_resolver.LocalFileResolver())


# ---------------------------------------------------------------------------
# Mock worker TCP server — for IPC tests
# ---------------------------------------------------------------------------
class _MockWorker:
    """JSON-line TCP server that mimics the Cloudium worker.

    Spins up on an ephemeral port; tests configure CloudiumFileResolver to
    connect to it. Supports custom op handlers per test.
    """

    def __init__(self, handlers=None):
        self.handlers = handlers or {"ping": lambda args: "pong"}
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self.host, self.port = self._sock.getsockname()
        self._sock.listen(8)
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        self._sock.settimeout(0.2)
        while not self._stop:
            try:
                client, _ = self._sock.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client):
        try:
            client.settimeout(2.0)
            buf = b""
            while b"\n" not in buf:
                chunk = client.recv(65536)
                if not chunk:
                    return
                buf += chunk
            line = buf.split(b"\n", 1)[0]
            req = json.loads(line.decode("utf-8"))
            op = req.get("op")
            args = req.get("args") or {}
            handler = self.handlers.get(op)
            if handler is None:
                resp = {"id": req.get("id"), "ok": False, "error": f"unknown_op: {op}"}
            else:
                try:
                    result = handler(args)
                    resp = {"id": req.get("id"), "ok": True, "result": result}
                except Exception as exc:  # noqa: BLE001
                    resp = {"id": req.get("id"), "ok": False, "error": f"{type(exc).__name__}: {exc}"}
            client.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass

    def close(self):
        self._stop = True
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2)


@pytest.fixture
def mock_worker():
    """기본 ping/exists/read_text 응답을 지원하는 mock worker."""
    def _read_bytes_chunked(args):
        # 청킹 protocol — backend가 offset/length로 chunk 요청
        full = b"mocked bytes"
        offset = int(args.get("offset", 0))
        length = args.get("length")
        if length is None or int(length) <= 0:
            chunk = full[offset:]
        else:
            chunk = full[offset:offset + int(length)]
        eof = (offset + len(chunk)) >= len(full)
        return {
            "data": base64.b64encode(chunk).decode("ascii"),
            "size": len(full),
            "eof": eof,
        }

    handlers = {
        "ping": lambda args: "pong",
        "exists": lambda args: True,
        "is_file": lambda args: True,
        "is_dir": lambda args: False,
        "read_text": lambda args: "mocked content",
        "read_bytes": _read_bytes_chunked,
        "list_dir": lambda args: ["a.txt", "b.txt"],
        "browse_file": lambda args: "/picked/file.xlsx",
        "browse_directory": lambda args: "/picked/dir",
    }
    w = _MockWorker(handlers)
    yield w
    w.close()


# ---------------------------------------------------------------------------
# is_gate_running — TCP ping + caching (Phase 2)
# ---------------------------------------------------------------------------
def test_is_gate_running_returns_true_when_worker_alive(mock_worker):
    file_resolver.invalidate_gate_cache()
    assert is_gate_running(host=mock_worker.host, port=mock_worker.port) is True


def test_is_gate_running_returns_false_when_worker_down():
    file_resolver.invalidate_gate_cache()
    # 비어있을 가능성 높은 port 사용
    assert is_gate_running(host="127.0.0.1", port=1, force=True) is False


def test_is_gate_running_uses_cache(mock_worker):
    file_resolver.invalidate_gate_cache()
    # 1차 ping
    assert is_gate_running(host=mock_worker.host, port=mock_worker.port) is True
    # worker 종료해도 캐시(TTL 1초) 내에서는 True 유지
    mock_worker.close()
    assert is_gate_running(host=mock_worker.host, port=mock_worker.port) is True


def test_is_gate_running_force_bypasses_cache(mock_worker):
    file_resolver.invalidate_gate_cache()
    assert is_gate_running(host=mock_worker.host, port=mock_worker.port) is True
    mock_worker.close()
    # force=True로 캐시 우회 → 실제 ping → False
    assert is_gate_running(host=mock_worker.host, port=mock_worker.port, force=True) is False


# ---------------------------------------------------------------------------
# CloudiumFileResolver._ensure_gate (worker IPC ping 기반)
# ---------------------------------------------------------------------------
def test_cloudium_blocks_read_when_worker_down(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello")
    # worker 미연결 (port 1) → ping 실패 → PermissionError
    r = CloudiumFileResolver(allowed_prefixes=str(tmp_path), host="127.0.0.1", port=1)
    with pytest.raises(PermissionError, match="worker 미응답"):
        r.read_text(str(f))
    with pytest.raises(PermissionError):
        r.read_bytes(str(f))
    with pytest.raises(PermissionError):
        r.exists(str(f))


def test_cloudium_allows_read_when_worker_alive(mock_worker, tmp_path):
    """worker IPC가 살아있으면 read는 worker 결과 반환."""
    r = CloudiumFileResolver(
        allowed_prefixes=str(tmp_path), host=mock_worker.host, port=mock_worker.port,
    )
    f = tmp_path / "x.txt"
    # mock worker는 read_text → "mocked content" 반환 (실제 파일 내용 무관)
    assert r.read_text(str(f)) == "mocked content"
    assert r.exists(str(f)) is True
    assert r.is_file(str(f)) is True


def test_cloudium_workspace_bypass_allows_project_root_paths(monkeypatch, tmp_path):
    """workspace bypass: backend project_root 하위는 allowed_prefixes 없이도 통과.

    회귀 차단 시나리오: 사용자가 cloudium 모드로 전환 후 Job 목록 / 분석 시
    backend가 reports/jobs/, .devops_pro_cache/, config/scm_registry.json 같은
    workspace 자체 파일을 read하는데 cloudium 차단됨 → 잘못된 false positive.
    """
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    fake_workspace = tmp_path / "fake_workspace"
    fake_workspace.mkdir()
    # 실제 workspace로 _PROJECT_ROOT를 가리키게 (autouse fixture 원복)
    monkeypatch.setattr(file_resolver, "_PROJECT_ROOT", fake_workspace)

    r = CloudiumFileResolver(allowed_prefixes="")  # 비어있어도 workspace는 통과
    # 통과 (예외 없음)
    r._check_allowed(str(fake_workspace / "reports" / "jobs.json"))
    r._check_allowed(str(fake_workspace / ".devops_pro_cache" / "x.bin"))
    r._check_allowed(str(fake_workspace))  # 자기 자신


def test_cloudium_workspace_bypass_does_not_leak_outside(monkeypatch, tmp_path):
    """workspace bypass가 workspace 외부 path까지 통과시키면 안 됨."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    fake_workspace = tmp_path / "fake_workspace"
    outside = tmp_path / "outside_share"
    fake_workspace.mkdir()
    outside.mkdir()
    monkeypatch.setattr(file_resolver, "_PROJECT_ROOT", fake_workspace)

    r = CloudiumFileResolver(allowed_prefixes="")
    with pytest.raises(PermissionError, match="workspace 외부|미설정"):
        r._check_allowed(str(outside / "secret.txt"))


# ── N9 fix (A): /api/scm/* exempt 검증 ─────────────────────────────────────


def test_middleware_exempts_scm_register_in_cloudium_mode():
    """N9 fix (A): cloudium 모드에서 외부 source_root로 SCM 등록 시 미들웨어가 차단하면 안 됨."""
    from backend.middleware import _is_exempt
    # 명시 화이트리스트
    assert _is_exempt("/api/scm/register") is True
    assert _is_exempt("/api/scm/update/my-id") is True
    assert _is_exempt("/api/scm/delete/my-id") is True
    assert _is_exempt("/api/scm/test/my-id") is True
    assert _is_exempt("/api/scm/audit/my-id") is True
    assert _is_exempt("/api/scm/status/my-id") is True
    assert _is_exempt("/api/scm/impact-jobs/my-id") is True
    assert _is_exempt("/api/scm/change-history/my-id") is True
    assert _is_exempt("/api/scm/my-id/link-docs") is True
    assert _is_exempt("/api/scm/list") is True
    # 일반 경로는 여전히 검사
    assert _is_exempt("/api/jenkins/uds/generate-async") is False
    assert _is_exempt("/api/local/sits/generate-async") is False


def test_middleware_does_not_blanket_exempt_all_scm_paths():
    """N14 fix: /api/scm/ 전체 startswith 우회 차단 — 미지의 신규 endpoint는 exempt 안 됨.

    명시 화이트리스트가 아닌 경로(/api/scm/sync, /api/scm/foo 등)는 PATH_KEYS scan
    대상이어야. D1 fix(deny-by-default) 정책 일관 유지.
    """
    from backend.middleware import _is_exempt
    # 미지의 SCM 신규 endpoint — 명시 추가되지 않으면 exempt 안 됨
    assert _is_exempt("/api/scm/sync") is False
    assert _is_exempt("/api/scm/refresh") is False
    assert _is_exempt("/api/scm/some-future-endpoint") is False
    # link-docs와 매칭하는 패턴이지만 정확히 일치 — 통과
    assert _is_exempt("/api/scm/x/link-docs-extra") is False  # link-docs로 끝나야 함


def test_cloudium_blocks_path_outside_allowed_prefixes(monkeypatch, tmp_path):
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    allowed = tmp_path / "allowed"
    blocked = tmp_path / "blocked"
    allowed.mkdir()
    blocked.mkdir()
    (blocked / "secret.txt").write_text("nope")
    r = CloudiumFileResolver(allowed_prefixes=str(allowed))
    with pytest.raises(PermissionError, match="허용되지 않은 경로"):
        r.read_text(str(blocked / "secret.txt"))


def test_cloudium_blocks_path_error_does_not_leak_prefixes(monkeypatch, tmp_path):
    """W4 회귀: 에러 메시지에 allowed_prefixes 전체 목록이 노출되면 안 됨."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    secret_prefix = tmp_path / "internal_share_xyz"
    secret_prefix.mkdir()
    blocked = tmp_path / "elsewhere"
    blocked.mkdir()
    (blocked / "f.txt").write_text("x")
    r = CloudiumFileResolver(allowed_prefixes=str(secret_prefix))
    try:
        r.read_text(str(blocked / "f.txt"))
        pytest.fail("PermissionError 기대")
    except PermissionError as e:
        # prefix 경로 자체가 메시지에 노출되면 정보 누출
        assert "internal_share_xyz" not in str(e)


def test_cloudium_get_config_includes_gate_state(monkeypatch, tmp_path):
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    r = CloudiumFileResolver(allowed_prefixes=str(tmp_path), gate_process="custom_gate.exe")
    cfg = r.get_config()
    assert cfg["mode"] == "cloudium"
    assert cfg["gate_process"] == "custom_gate.exe"
    assert cfg["gate_running"] is True
    assert cfg["read_only"] is True


def test_cloudium_uses_default_gate_process_when_unset():
    r = CloudiumFileResolver()
    assert r.gate_process == DEFAULT_GATE_PROCESS


def test_cloudium_env_override_for_gate(monkeypatch):
    monkeypatch.setenv("CLOUDIUM_GATE_PROCESS", "my_app.exe")
    r = CloudiumFileResolver()
    assert r.gate_process == "my_app.exe"


def test_local_resolver_unchanged():
    """LocalFileResolver 회귀 — 게이트 검사 없이 동작해야 함."""
    r = LocalFileResolver()
    assert r.mode == "local"
    cfg = r.get_config()
    assert "gate_running" not in cfg


# ---------------------------------------------------------------------------
# IPC 프로토콜 견고성 — Phase 2 검증 (tasklist 폴백 테스트는 Phase 2에서 폐기)
# ---------------------------------------------------------------------------
def test_ipc_returns_unknown_op_error(tmp_path):
    """worker가 모르는 op에 unknown_op 에러 반환 → backend가 OSError로 raise."""
    handlers = {"ping": lambda args: "pong"}  # exists/read 미정의
    w = _MockWorker(handlers)
    try:
        r = CloudiumFileResolver(allowed_prefixes=str(tmp_path), host=w.host, port=w.port)
        with pytest.raises(OSError, match="unknown_op"):
            r.exists(str(tmp_path / "x"))
    finally:
        w.close()


def test_ipc_translates_filenotfound_error(tmp_path):
    """worker가 FileNotFoundError 직렬화 → backend가 동일 예외로 raise (endpoint 호환)."""
    def _fail(args):
        raise FileNotFoundError(f"no such file: {args.get('path')}")
    w = _MockWorker({"ping": lambda a: "pong", "read_text": _fail})
    try:
        r = CloudiumFileResolver(allowed_prefixes=str(tmp_path), host=w.host, port=w.port)
        with pytest.raises(FileNotFoundError):
            r.read_text(str(tmp_path / "missing"))
    finally:
        w.close()


def test_ipc_translates_permission_error(tmp_path):
    def _fail(args):
        raise PermissionError("denied by OS")
    w = _MockWorker({"ping": lambda a: "pong", "read_text": _fail})
    try:
        r = CloudiumFileResolver(allowed_prefixes=str(tmp_path), host=w.host, port=w.port)
        with pytest.raises(PermissionError):
            r.read_text(str(tmp_path / "some"))
    finally:
        w.close()


def test_ipc_read_bytes_decodes_base64(mock_worker, tmp_path):
    r = CloudiumFileResolver(allowed_prefixes=str(tmp_path),
                             host=mock_worker.host, port=mock_worker.port)
    assert r.read_bytes(str(tmp_path / "x.bin")) == b"mocked bytes"


# ---------------------------------------------------------------------------
# C2: deny-by-default — allowed_prefixes 미설정 시 차단
# ---------------------------------------------------------------------------
def test_cloudium_empty_allowed_prefixes_blocks_all(monkeypatch, tmp_path):
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    monkeypatch.delenv("CLOUDIUM_ALLOWED_PREFIXES", raising=False)
    f = tmp_path / "x.txt"
    f.write_text("hi")
    r = CloudiumFileResolver()  # allowed_prefixes 미설정
    with pytest.raises(PermissionError, match="allowed_prefixes 미설정"):
        r.read_text(str(f))
    with pytest.raises(PermissionError, match="allowed_prefixes 미설정"):
        r.exists(str(f))


# ---------------------------------------------------------------------------
# W2: prefix 비교가 substring 매칭이 아니라 boundary-aware인지
# ---------------------------------------------------------------------------
def test_cloudium_prefix_substring_does_not_match(monkeypatch, tmp_path):
    """allowed=/data 일 때 /data_other/x 가 우연히 매칭되면 안 됨."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    allowed = tmp_path / "data"
    other = tmp_path / "data_other"
    allowed.mkdir()
    other.mkdir()
    (other / "leak.txt").write_text("nope")
    r = CloudiumFileResolver(allowed_prefixes=str(allowed))
    with pytest.raises(PermissionError, match="허용되지 않은 경로"):
        r.read_text(str(other / "leak.txt"))


def test_cloudium_prefix_exact_match_succeeds(mock_worker, tmp_path):
    """prefix 자체와 동일한 경로도 허용되어야 함."""
    d = tmp_path / "data"
    d.mkdir()
    r = CloudiumFileResolver(allowed_prefixes=str(d),
                             host=mock_worker.host, port=mock_worker.port)
    # 디렉토리 자체에 대한 exists 검사 — _check_allowed 통과 후 mock worker가 True 반환
    assert r.exists(str(d)) is True


# ---------------------------------------------------------------------------
# W3: gate_process Pydantic 정규식 검증
# ---------------------------------------------------------------------------
def test_file_mode_request_rejects_invalid_gate_process():
    from pydantic import ValidationError
    from backend.routers.health import FileModeRequest
    bad_values = [
        "../../evil.exe",
        "evil & cmd.exe",
        "no_extension",
        "two words.exe",
        "tab\tname.exe",
    ]
    for bad in bad_values:
        with pytest.raises(ValidationError):
            FileModeRequest(mode="cloudium", gate_process=bad)


def test_file_mode_request_accepts_valid_gate_process():
    from backend.routers.health import FileModeRequest
    good = ["excel_rename_gui_v2.exe", "my-app.exe", "App.Name.exe", "x.exe"]
    for v in good:
        m = FileModeRequest(mode="cloudium", gate_process=v)
        assert m.gate_process == v


def test_file_mode_request_allows_empty_or_none_gate_process():
    from backend.routers.health import FileModeRequest
    # None/빈 문자열은 fallback (env/기본값)을 의미하므로 허용
    assert FileModeRequest(mode="cloudium", gate_process=None).gate_process is None
    assert FileModeRequest(mode="cloudium", gate_process="").gate_process == ""


# ---------------------------------------------------------------------------
# X5: write/delete/append 메서드가 모두 raise하는지
# ---------------------------------------------------------------------------
def test_cloudium_explicit_write_methods_all_raise(monkeypatch, tmp_path):
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    r = CloudiumFileResolver(allowed_prefixes=str(tmp_path))
    p = str(tmp_path / "x.txt")
    # 명시 시그너처에 맞춰 호출
    with pytest.raises(PermissionError, match="read-only"):
        r.write_text(p, "data")
    with pytest.raises(PermissionError, match="read-only"):
        r.write_bytes(p, b"data")
    with pytest.raises(PermissionError, match="read-only"):
        r.delete(p)
    with pytest.raises(PermissionError, match="read-only"):
        r.remove(p)
    with pytest.raises(PermissionError, match="read-only"):
        r.unlink(p)
    with pytest.raises(PermissionError, match="read-only"):
        r.append(p, "data")


# ---------------------------------------------------------------------------
# C1: preview-excel / preview-image이 Cloudium 게이트 미실행 시 403
# ---------------------------------------------------------------------------
def test_preview_excel_blocked_when_cloudium_gate_not_running(monkeypatch, tmp_path):
    from backend.services.file_resolver import set_resolver, CloudiumFileResolver, LocalFileResolver

    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: False)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        f = tmp_path / "x.xlsx"
        f.write_bytes(b"not a real xlsx")
        r = c.post("/api/preview-excel", json={"path": str(f)})
        assert r.status_code == 403
        assert "게이트 미실행" in r.text or "Cloudium" in r.text
    finally:
        set_resolver(LocalFileResolver())


def test_preview_image_blocked_when_cloudium_path_not_allowed(monkeypatch, tmp_path):
    from backend.services.file_resolver import set_resolver, CloudiumFileResolver, LocalFileResolver

    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    allowed = tmp_path / "ok"
    blocked = tmp_path / "block"
    allowed.mkdir()
    blocked.mkdir()
    (blocked / "secret.docx").write_bytes(b"x")
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(allowed)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        r = c.get("/api/preview-image", params={"path": str(blocked / "secret.docx"), "image_id": "rId1"})
        assert r.status_code == 403
        assert "허용되지 않은 경로" in r.text or "Cloudium" in r.text
    finally:
        set_resolver(LocalFileResolver())


def test_preview_excel_allows_through_gate_and_whitelist(monkeypatch, tmp_path):
    """게이트 + 화이트리스트 모두 통과하면 미들웨어 단계에서 차단되지 않음을 확인.

    C3 fix 이후 endpoint도 enforce_resolver_access + worker IPC를 시도하므로
    mock worker 없는 환경에서는 endpoint 단계에서 OSError → 403 반환.
    핵심 검증은 미들웨어가 CLOUDIUM_BLOCKED로 차단하지 않는 것.
    """
    from backend.services.file_resolver import set_resolver, CloudiumFileResolver, LocalFileResolver

    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        r = c.post("/api/preview-excel", json={"path": str(tmp_path / "nope.xlsx")})
        body = r.json()
        # 미들웨어가 path 화이트리스트를 통과시켰음 — CLOUDIUM_BLOCKED 코드 아님
        assert body.get("code") != "CLOUDIUM_BLOCKED", (
            f"미들웨어가 차단하면 안 됨 (path 화이트리스트 hit): {body}"
        )
    finally:
        set_resolver(LocalFileResolver())


# ---------------------------------------------------------------------------
# W1: atomic snapshot — _gate_cache가 tuple로 통째 교체되는지
# ---------------------------------------------------------------------------
def test_gate_cache_is_atomic_tuple():
    """_gate_cache는 tuple로 단일 할당돼야 한다 (race-free)."""
    assert isinstance(file_resolver._gate_cache, tuple)
    assert len(file_resolver._gate_cache) == 3
    name, running, ts = file_resolver._gate_cache
    assert isinstance(name, str)
    assert isinstance(running, bool)
    assert isinstance(ts, float)


def test_gate_cache_concurrent_reads_see_consistent_snapshot():
    """동시 read에서 부분 갱신된 (이전 running, 새 name) 조합을 보면 안 됨.

    100회 갱신을 인터리브해도 항상 일관된 (name, running, ts) tuple만 관찰돼야 한다.
    """
    for _ in range(100):
        snap = file_resolver._gate_cache
        # snapshot은 길이 3, 모든 필드가 일관 타입
        assert isinstance(snap, tuple) and len(snap) == 3
        # 부분 갱신된 dict가 아니라 tuple이므로 atomic
        assert isinstance(snap[0], str)
        assert isinstance(snap[1], bool)
        assert isinstance(snap[2], float)


# ---------------------------------------------------------------------------
# TTL 1초 단축 검증
# ---------------------------------------------------------------------------
def test_gate_cache_ttl_is_one_second():
    """TTL이 1초로 단축됐는지 명시 검증 — stale 윈도우 회귀 방지."""
    assert file_resolver._GATE_CACHE_TTL == 1.0


def test_invalidate_gate_cache_resets_snapshot(mock_worker):
    """invalidate_gate_cache 호출 시 다음 is_gate_running이 캐시 무시하고 재검사 (IPC ping)."""
    calls = {"n": 0}
    real_handler = mock_worker.handlers["ping"]
    def _counted_ping(args):
        calls["n"] += 1
        return real_handler(args)
    mock_worker.handlers["ping"] = _counted_ping

    file_resolver.invalidate_gate_cache()
    file_resolver.is_gate_running(host=mock_worker.host, port=mock_worker.port)
    n_after_first = calls["n"]
    # 캐시 hit — ping 안 함
    file_resolver.is_gate_running(host=mock_worker.host, port=mock_worker.port)
    assert calls["n"] == n_after_first
    file_resolver.invalidate_gate_cache()
    file_resolver.is_gate_running(host=mock_worker.host, port=mock_worker.port)
    assert calls["n"] == n_after_first + 1


# ---------------------------------------------------------------------------
# set_resolver 노출 축소 — __all__에서 제외, public API 명시
# ---------------------------------------------------------------------------
def test_set_resolver_excluded_from_all():
    """set_resolver는 __all__에서 제외 — 스타글로브 import로 노출되지 않음."""
    assert "set_resolver" not in file_resolver.__all__
    # 그러나 명시 import는 허용 (테스트/내부 사용)
    assert hasattr(file_resolver, "set_resolver")


def test_public_api_in_all():
    """public API 항목이 __all__에 모두 있는지."""
    expected = {
        "FileResolver", "LocalFileResolver", "CloudiumFileResolver",
        "get_resolver", "switch_mode", "is_gate_running",
        "invalidate_gate_cache", "DEFAULT_GATE_PROCESS",
    }
    assert expected.issubset(set(file_resolver.__all__))


def test_set_resolver_invalidates_gate_cache():
    """set_resolver는 게이트 캐시도 무효화해야 — 모드 전환 후 stale 캐시로 잘못된 read 허용 방지."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver

    # 캐시에 stale True 넣기
    file_resolver._gate_cache = ("excel_rename_gui_v2.exe", True, 99999999.0)
    set_resolver(LocalFileResolver())
    # 캐시가 초기화돼야 함
    assert file_resolver._gate_cache == ("", False, 0.0)


# ---------------------------------------------------------------------------
# D5: 명시 시그너처 — write 메서드는 raise 전에 시그너처 mismatch를 정적 검사기가 잡을 수 있음
# ---------------------------------------------------------------------------
def test_write_methods_have_explicit_signatures(monkeypatch, tmp_path):
    """write_text 등이 (*_a, **_kw)가 아니라 명시 시그너처를 가져야 한다.

    inspect.signature로 시그너처를 검사 — 정적 검사기와 일치한지.
    """
    import inspect
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    r = CloudiumFileResolver(allowed_prefixes=str(tmp_path))

    sig_write_text = inspect.signature(r.write_text)
    params = list(sig_write_text.parameters.keys())
    assert "path" in params, f"write_text 시그너처가 명시적 path 인자 부재: {params}"
    assert "data" in params

    sig_delete = inspect.signature(r.delete)
    assert "path" in sig_delete.parameters

    # 잘못된 인자 개수로 호출 시 TypeError (시그너처가 명시적이라는 증거)
    with pytest.raises(TypeError):
        r.delete(str(tmp_path), "extra_unexpected_arg")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# D8: inspect.stack 가드 — INFO 미활성 시 stack 호출 안 함
# ---------------------------------------------------------------------------
def test_set_resolver_skips_inspect_when_info_disabled(monkeypatch):
    """logger INFO 미활성 시 inspect.stack() 호출 비용을 회피해야 한다."""
    import inspect as _inspect
    from backend.services.file_resolver import set_resolver, LocalFileResolver

    calls = {"stack": 0}
    real_stack = _inspect.stack

    def _counting_stack(*a, **kw):
        calls["stack"] += 1
        return real_stack(*a, **kw)

    monkeypatch.setattr(_inspect, "stack", _counting_stack)
    # INFO 비활성화
    file_resolver._logger.setLevel(logging.WARNING)
    try:
        set_resolver(LocalFileResolver())
        assert calls["stack"] == 0, "INFO 미활성 시 inspect.stack 호출되면 안 됨"
    finally:
        file_resolver._logger.setLevel(logging.INFO)


def test_set_resolver_uses_inspect_when_info_enabled(monkeypatch):
    """logger INFO 활성 시 caller 정보 수집 — 운영 추적성."""
    import inspect as _inspect
    from backend.services.file_resolver import set_resolver, LocalFileResolver

    calls = {"stack": 0}
    real_stack = _inspect.stack

    def _counting_stack(*a, **kw):
        calls["stack"] += 1
        return real_stack(*a, **kw)

    monkeypatch.setattr(_inspect, "stack", _counting_stack)
    file_resolver._logger.setLevel(logging.INFO)
    set_resolver(LocalFileResolver())
    assert calls["stack"] >= 1


# ---------------------------------------------------------------------------
# D1: CloudiumGateMiddleware — body/query 자동 검사
# ---------------------------------------------------------------------------
def test_middleware_blocks_body_path_key_when_gate_off(monkeypatch, tmp_path):
    """미들웨어가 body의 'srs_path' 같은 PATH_KEYS를 검사 — 196곳 우회 차단."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: False)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        # /api/jenkins/uds/extract-mapping 같은 endpoint는 body에 uds_path 받음
        # 미들웨어가 PATH_KEYS hit으로 게이트 검사 → 403
        # endpoint 존재 여부와 무관하게 미들웨어 단계에서 403 차단되어야 함
        r = c.post("/api/anything", json={"uds_path": str(tmp_path / "x.docx")})
        assert r.status_code == 403
        body = r.json()
        assert body.get("code") == "CLOUDIUM_BLOCKED"
        assert "detail" in body
    finally:
        set_resolver(LocalFileResolver())


def test_middleware_blocks_query_path_key_when_path_not_allowed(monkeypatch, tmp_path):
    """미들웨어가 query string의 PATH_KEYS도 검사."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    allowed = tmp_path / "ok"
    blocked = tmp_path / "block"
    allowed.mkdir()
    blocked.mkdir()
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(allowed)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        # GET /api/preview-image?path=...&image_id=...  — query path 검사
        r = c.get("/api/preview-image",
                  params={"path": str(blocked / "x.docx"), "image_id": "rId1"})
        assert r.status_code == 403
        assert "CLOUDIUM_BLOCKED" in r.text or "허용되지 않은 경로" in r.text
    finally:
        set_resolver(LocalFileResolver())


def test_middleware_allows_local_mode(monkeypatch, tmp_path):
    """LOCAL 모드면 미들웨어 통과 — Cloudium 비활성 시 어떤 path든 허용."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver
    set_resolver(LocalFileResolver())

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        # 존재하지 않는 endpoint여도 미들웨어가 차단하면 403, 차단 안 하면 404 (또는 endpoint 응답)
        r = c.post("/api/anything", json={"srs_path": "//corp/secret/anywhere.txt"})
        # 403이 아닌 다른 코드 (404 등) — 미들웨어 통과
        assert r.status_code != 403
    finally:
        set_resolver(LocalFileResolver())


def test_middleware_exempt_path_passes_in_cloudium(monkeypatch, tmp_path):
    """/api/file-mode 등 exempt path는 cloudium 모드여도 미들웨어 통과해야 — chicken-and-egg 방지."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: False)  # 게이트 OFF
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        # /api/file-mode GET은 게이트 OFF여도 응답해야 함 (모드 조회 자체)
        r = c.get("/api/file-mode")
        assert r.status_code == 200
        # /api/health도 통과
        r = c.get("/api/health")
        assert r.status_code == 200
    finally:
        set_resolver(LocalFileResolver())


def test_middleware_body_can_be_reread_by_endpoint(monkeypatch, tmp_path):
    """미들웨어가 body를 읽고도 endpoint가 다시 받을 수 있어야 — receive 재구성.

    C3 fix 이후 endpoint도 worker IPC 시도 → mock worker 없으면 403. 핵심
    검증은 (1) body 재구성 실패에 의한 422가 아님, (2) 미들웨어 차단(CLOUDIUM_BLOCKED)
    아님 — 즉 endpoint가 path를 정상 수신했다는 사실.
    """
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        r = c.post("/api/preview-excel",
                   json={"path": str(tmp_path / "exists.xlsx")})
        assert r.status_code != 422, (
            f"body 재구성 실패 — endpoint가 path를 못 받음: {r.status_code} {r.text[:200]}"
        )
        body = r.json()
        # 미들웨어 차단이 아닌 endpoint 도달이어야 함 (path 화이트리스트 통과)
        assert body.get("code") != "CLOUDIUM_BLOCKED", (
            f"미들웨어 차단이 아닌 endpoint 도달이어야 함: {body}"
        )
    finally:
        set_resolver(LocalFileResolver())


def test_middleware_recursive_dict_scan(monkeypatch, tmp_path):
    """중첩된 dict의 PATH_KEYS도 검사 (예: { "config": { "path": ".." } })."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: False)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        r = c.post("/api/anything",
                   json={"config": {"file_path": str(tmp_path / "secret.txt")}})
        assert r.status_code == 403
    finally:
        set_resolver(LocalFileResolver())


# ---------------------------------------------------------------------------
# C1: 응답 형식 통일 — frontend api.js의 detail 매칭 일관성
# ---------------------------------------------------------------------------
def test_middleware_response_uses_detail_key_for_frontend_compat(monkeypatch, tmp_path):
    """미들웨어 차단 응답이 frontend api.js detail 키와 호환돼야 함.

    api.js: if (j.detail) msg = j.detail;  → detail 우선 추출.
    """
    from backend.services.file_resolver import set_resolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: False)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    from starlette.testclient import TestClient
    from backend.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.headers["X-User"] = "test"
    r = c.post("/api/anything", json={"path": str(tmp_path / "x")})
    assert r.status_code == 403
    body = r.json()
    # frontend api.js는 j.detail을 우선 본다
    assert "detail" in body, f"응답에 detail 키 없음: {body}"
    assert isinstance(body["detail"], str) and body["detail"]
    assert body.get("code") == "CLOUDIUM_BLOCKED"
    assert body.get("ok") is False


# ---------------------------------------------------------------------------
# C2: multipart/form-data 우회 차단
# ---------------------------------------------------------------------------
def test_middleware_blocks_multipart_form_path_field(monkeypatch, tmp_path):
    """multipart/form-data로 cache_root, template_path 등 보내도 게이트 검사 작동."""
    from backend.services.file_resolver import set_resolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: False)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    from starlette.testclient import TestClient
    from backend.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.headers["X-User"] = "test"
    # multipart/form-data 요청 — files= 파라미터를 쓰면 starlette/httpx가 자동 multipart
    files = {"dummy_file": ("a.txt", b"data", "text/plain")}
    data = {"cache_root": str(tmp_path / "leak"), "template_path": str(tmp_path / "y")}
    r = c.post("/api/anything", data=data, files=files)
    assert r.status_code == 403
    body = r.json()
    assert body.get("code") == "CLOUDIUM_BLOCKED"


def test_middleware_blocks_urlencoded_form_path_field(monkeypatch, tmp_path):
    """application/x-www-form-urlencoded도 검사."""
    from backend.services.file_resolver import set_resolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: False)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    from starlette.testclient import TestClient
    from backend.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.headers["X-User"] = "test"
    # data={...} + files= 없음 → urlencoded
    r = c.post("/api/anything", data={"source_root": "//corp/secret"})
    assert r.status_code == 403
    assert r.json().get("code") == "CLOUDIUM_BLOCKED"


# ---------------------------------------------------------------------------
# W4: check_access public API
# ---------------------------------------------------------------------------
def test_check_access_is_public_method(monkeypatch, tmp_path):
    """check_access는 public — 외부 layer가 protected 메서드에 의존하지 않아야 함."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    r = CloudiumFileResolver(allowed_prefixes=str(tmp_path))
    # 정상 호출은 None 반환 (raise 없음)
    assert r.check_access(str(tmp_path / "x.txt")) is None


def test_check_access_raises_on_gate_off(tmp_path):
    # worker 미연결 (port 1) → ping 실패 → PermissionError
    r = CloudiumFileResolver(allowed_prefixes=str(tmp_path), host="127.0.0.1", port=1)
    with pytest.raises(PermissionError, match="worker 미응답"):
        r.check_access(str(tmp_path / "x.txt"))


def test_check_access_raises_on_blocked_path(monkeypatch, tmp_path):
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    allowed = tmp_path / "ok"
    allowed.mkdir()
    r = CloudiumFileResolver(allowed_prefixes=str(allowed))
    with pytest.raises(PermissionError, match="허용되지 않은 경로"):
        r.check_access(str(tmp_path / "elsewhere.txt"))


# ---------------------------------------------------------------------------
# W3: autouse fixture가 resolver도 reset
# ---------------------------------------------------------------------------
def test_autouse_fixture_resets_resolver_to_local():
    """이전 테스트가 cloudium으로 set_resolver를 바꿨어도 다음 테스트는 LOCAL로 시작."""
    # autouse fixture가 매 테스트 시작 시 LocalFileResolver로 reset함을 검증
    resolver = file_resolver.get_resolver()
    assert isinstance(resolver, file_resolver.LocalFileResolver), \
        f"테스트 시작 시 resolver는 Local이어야 하는데 {type(resolver).__name__} 발견"


# ---------------------------------------------------------------------------
# W2: 라우터 path 키 회귀 테스트 — PATH_KEYS 누락 자동 탐지
# ---------------------------------------------------------------------------
def test_all_router_user_input_path_keys_are_in_path_keys_whitelist():
    """라우터의 사용자 입력 path 키가 모두 _CLOUDIUM_PATH_KEYS에 등록되어 있는지 검증.

    검사 패턴:
      - (payload|body|req).get("XXX_path") / .get("XXX_root") 등 — JSON body
      - XXX_path: str = Form("") — multipart form field

    누락되면 미들웨어가 검사 못 해 Cloudium 모드에서도 통과 → 정책 우회 결손.
    이 테스트는 새 endpoint가 새 키 이름을 도입할 때 즉시 실패해야 한다.
    """
    import re
    from pathlib import Path as _P
    from backend.middleware import _CLOUDIUM_PATH_KEYS, _CLOUDIUM_MULTI_PATH_KEYS

    routers_dir = _P(__file__).resolve().parents[2] / "backend" / "routers"
    assert routers_dir.is_dir(), f"라우터 디렉토리 못 찾음: {routers_dir}"

    # 사용자 입력 dict 변수 이름들 (응답/내부 dict 제외)
    user_input_dicts = ("payload", "body", "req", "request_body")
    get_pattern = re.compile(
        r"(?:" + "|".join(user_input_dicts) + r")"
        r"\.get\([\"'](\w+)[\"']"
    )
    # multipart form: `XXX: str = Form(...)` 또는 `XXX: UploadFile = File(...)`
    form_pattern = re.compile(
        r"^\s*(\w+)\s*:\s*(?:str|Optional\[str\])\s*=\s*Form\(",
        re.MULTILINE,
    )

    # path 의미를 가진 키 접미사 (false positive 줄이기 위해 보수적으로)
    # **D2 fix**: `_paths` 복수형 포함 — req_paths 같은 multi-path Form field도 검출.
    path_suffixes = ("_path", "_paths", "_root", "_dir", "_folder", "_target")
    path_exact_names = {"path", "target", "folder", "root"}

    found_keys: set[str] = set()
    for py_file in routers_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for m in get_pattern.finditer(text):
            key = m.group(1)
            if key in path_exact_names or any(key.endswith(s) for s in path_suffixes):
                found_keys.add(key)
        for m in form_pattern.finditer(text):
            key = m.group(1)
            if key in path_exact_names or any(key.endswith(s) for s in path_suffixes):
                found_keys.add(key)

    # PATH_KEYS (single-string) 또는 MULTI_PATH_KEYS (콤마/세미콜론 split) 둘 중 하나에 들어 있으면 통과
    whitelist = _CLOUDIUM_PATH_KEYS | _CLOUDIUM_MULTI_PATH_KEYS
    missing = found_keys - whitelist
    assert not missing, (
        f"라우터에서 사용되는 사용자 입력 path 키가 PATH_KEYS / MULTI_PATH_KEYS 어디에도 누락됨: "
        f"{sorted(missing)}. backend/middleware.py의 _CLOUDIUM_PATH_KEYS 또는 "
        f"_CLOUDIUM_MULTI_PATH_KEYS에 추가하거나, path가 아니라면 path_exact_names/path_suffixes "
        f"화이트리스트 조정 필요."
    )


def test_validation_and_residual_report_path_keys_blocked_by_middleware(monkeypatch, tmp_path):
    """W2 회귀 — validation_report_path / residual_report_path 누락이 다시 발생하지 않도록.

    payload에 두 키가 들어오면 미들웨어가 게이트 검사로 403을 내야 한다.
    PATH_KEYS에 빠지면 통과되어 다운스트림에서 파일 접근 시점에서야 차단됨.
    """
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: False)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"

        # validation_report_path
        r = c.post("/api/anything",
                   json={"validation_report_path": str(tmp_path / "validation.html")})
        assert r.status_code == 403, "validation_report_path가 미들웨어에서 검사되지 않음"
        assert r.json().get("code") == "CLOUDIUM_BLOCKED"

        # residual_report_path
        r = c.post("/api/anything",
                   json={"residual_report_path": str(tmp_path / "residual.html")})
        assert r.status_code == 403, "residual_report_path가 미들웨어에서 검사되지 않음"
        assert r.json().get("code") == "CLOUDIUM_BLOCKED"
    finally:
        set_resolver(LocalFileResolver())


# ---------------------------------------------------------------------------
# D1: middleware exempt 정확 매칭 — /api/file-mode/* 우회 차단
# ---------------------------------------------------------------------------
def test_middleware_exempt_does_not_match_unknown_file_mode_subpath(monkeypatch, tmp_path):
    """D1 회귀 — `/api/file-mode/anything-new` 미지의 path는 미들웨어 검사를 받아야 함.

    과거 startswith 매칭은 신규 endpoint를 자동 우회시켰음. frozenset + 정확 매치로
    명시 endpoint(`browse-file`/`check-access`)만 통과. 미지의 sub-path는 path 화이트리스트 검사.
    """
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: False)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        # 미들웨어가 차단해야 함 (미지의 file-mode sub-path는 더 이상 exempt 아님)
        r = c.post("/api/file-mode/anything-new",
                   json={"path": str(tmp_path / "leak.txt")})
        assert r.status_code == 403, (
            f"D1 회귀: /api/file-mode/* 미지 path가 미들웨어 검사를 받아야 함: {r.text[:200]}"
        )
        assert r.json().get("code") == "CLOUDIUM_BLOCKED"
    finally:
        set_resolver(LocalFileResolver())


def test_middleware_exempt_still_passes_browse_file_and_check_access(monkeypatch, tmp_path):
    """D1 — 명시 화이트리스트 endpoint는 cloudium 모드에서도 통과해야 함."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: False)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        # /api/file-mode/check-access는 게이트 OFF 상태에서도 200 반환 (모드 조회)
        r = c.post("/api/file-mode/check-access", json={})
        assert r.status_code == 200, f"check-access exempt 실패: {r.text[:200]}"
    finally:
        set_resolver(LocalFileResolver())


# ---------------------------------------------------------------------------
# D2: req_paths multi-path 미들웨어 검사
# ---------------------------------------------------------------------------
def test_multi_path_form_field_blocked_by_middleware(monkeypatch, tmp_path):
    """D2 회귀 — `req_paths` 콤마/세미콜론 multi-path가 미들웨어에서 split 후 각각 검사."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    allowed = tmp_path / "ok"
    blocked = tmp_path / "block"
    allowed.mkdir()
    blocked.mkdir()
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(allowed)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        # multipart/form-data로 콤마 구분 multi-path. 첫 path는 allowed, 두 번째는 blocked
        # → 미들웨어가 split 후 두 번째 검사에서 차단
        files = {"dummy": ("a.txt", b"d", "text/plain")}
        data = {"req_paths": f"{allowed / 'a.docx'},{blocked / 'b.docx'}"}
        r = c.post("/api/anything", data=data, files=files)
        assert r.status_code == 403, f"req_paths multi-path 차단 실패: {r.text[:200]}"
        assert r.json().get("code") == "CLOUDIUM_BLOCKED"
    finally:
        set_resolver(LocalFileResolver())


def test_multi_path_form_field_passes_when_all_allowed(monkeypatch, tmp_path):
    """D2 — 모든 element가 allowed_prefix 안이면 미들웨어 통과."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        files = {"dummy": ("a.txt", b"d", "text/plain")}
        data = {"req_paths": f"{tmp_path / 'a.docx'},{tmp_path / 'b.docx'}"}
        r = c.post("/api/anything", data=data, files=files)
        # 미들웨어는 통과 — 미지의 endpoint라 starlette 404 또는 endpoint 응답
        assert r.status_code != 403 or r.json().get("code") != "CLOUDIUM_BLOCKED", (
            f"모두 allowed인데 미들웨어가 차단: {r.text[:200]}"
        )
    finally:
        set_resolver(LocalFileResolver())


# ---------------------------------------------------------------------------
# D3: cloudium 모드에서 UploadFile 차단
# ---------------------------------------------------------------------------
def test_reject_upload_in_cloudium_blocks_with_filename(monkeypatch, tmp_path):
    """D3 회귀 — cloudium 모드 + UploadFile (filename 있음) → 403."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    from backend.services.resolver_helpers import reject_upload_in_cloudium
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    class _FakeUpload:
        def __init__(self, name):
            self.filename = name

    try:
        # filename 있는 UploadFile은 거부
        with pytest.raises(Exception) as excinfo:
            reject_upload_in_cloudium(_FakeUpload("evil.docx"))
        # HTTPException 또는 동등 검증
        assert "403" in str(excinfo.value) or "Cloudium" in str(excinfo.value)
    finally:
        set_resolver(LocalFileResolver())


def test_reject_upload_in_cloudium_passes_in_local_mode(tmp_path):
    """D3 — local 모드면 no-op (어떤 업로드도 통과)."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver
    from backend.services.resolver_helpers import reject_upload_in_cloudium
    set_resolver(LocalFileResolver())

    class _FakeUpload:
        def __init__(self, name):
            self.filename = name

    try:
        # local 모드면 raise 없음
        reject_upload_in_cloudium(_FakeUpload("ok.docx"), None, _FakeUpload(""))
    finally:
        set_resolver(LocalFileResolver())


def test_reject_upload_in_cloudium_passes_empty_filename(monkeypatch, tmp_path):
    """D3 — UploadFile 인자가 None이거나 filename 없으면 통과 (default=None 케이스)."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    from backend.services.resolver_helpers import reject_upload_in_cloudium
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    class _FakeUpload:
        def __init__(self, name):
            self.filename = name

    try:
        # None 또는 빈 filename은 통과
        reject_upload_in_cloudium(None, _FakeUpload(""), _FakeUpload(None))
    finally:
        set_resolver(LocalFileResolver())


# ---------------------------------------------------------------------------
# W3: platform-aware lowercase 정규화
# ---------------------------------------------------------------------------
def test_check_allowed_case_sensitive_on_non_windows(monkeypatch, tmp_path):
    """W3 회귀 — non-Windows에서는 case-sensitive 비교로 잘못된 prefix 매칭 차단."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    monkeypatch.setattr(file_resolver.sys, "platform", "linux")
    # allowed=`/mnt/Project`, 사용자가 `/mnt/project/secret.txt` 시도 (대소문자 다름)
    r = CloudiumFileResolver(allowed_prefixes="/mnt/Project")
    with pytest.raises(PermissionError, match="허용되지 않은 경로"):
        r._check_allowed("/mnt/project/secret.txt")


def test_check_allowed_case_insensitive_on_windows(monkeypatch, tmp_path):
    """W3 — Windows는 lowercase 정규화 유지 (경로 대소문자 무관 매칭)."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    monkeypatch.setattr(file_resolver.sys, "platform", "win32")
    r = CloudiumFileResolver(allowed_prefixes="C:/Project")
    # 통과 (raise 없음)
    r._check_allowed("C:/PROJECT/file.txt")


# ---------------------------------------------------------------------------
# W4: ContextVar 다중 path 마킹
# ---------------------------------------------------------------------------
def test_mark_path_validated_supports_multiple_paths():
    """W4 회귀 — mark_path_validated가 list/tuple/frozenset 받아 모두 마킹."""
    from backend.services.file_resolver import (
        mark_path_validated, reset_path_validated, _path_already_validated,
    )
    paths = ["/p1", "/p2", "/p3"]
    token = mark_path_validated(paths)
    try:
        already = _path_already_validated.get()
        assert already is not None
        assert "/p1" in already
        assert "/p2" in already
        assert "/p3" in already
    finally:
        reset_path_validated(token)


def test_gate_then_allow_skips_when_path_in_marked_set(monkeypatch, tmp_path):
    """W4 — _gate_then_allow가 마킹된 frozenset 멤버십 검사로 ping 생략."""
    from backend.services.file_resolver import (
        CloudiumFileResolver, mark_path_validated, reset_path_validated,
    )
    # is_gate_running를 raise하도록 설정 — 호출되면 fail
    def _raise(*_a, **_k):
        raise AssertionError("ping이 호출되면 안 됨 — ContextVar로 skip되어야")
    monkeypatch.setattr(file_resolver, "is_gate_running", _raise)

    r = CloudiumFileResolver(allowed_prefixes=str(tmp_path))
    token = mark_path_validated(["/p1", "/p2"])
    try:
        r._gate_then_allow("/p2")  # ping 안 호출돼야 — frozenset 멤버
    finally:
        reset_path_validated(token)


# ---------------------------------------------------------------------------
# W5: read_bytes string 응답 silent truncation 차단
# ---------------------------------------------------------------------------
def test_read_bytes_raises_when_worker_returns_legacy_string(monkeypatch, tmp_path):
    """W5 회귀 — 옛 worker(string 반환)는 4MB silent truncation 위험. 명시 PermissionError."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    handlers = {
        "ping": lambda args: "pong",
        # legacy: read_bytes가 string 반환
        "read_bytes": lambda args: base64.b64encode(b"old protocol bytes").decode("ascii"),
    }
    w = _MockWorker(handlers)
    try:
        r = CloudiumFileResolver(
            allowed_prefixes=str(tmp_path), host=w.host, port=w.port,
        )
        # ContextVar 마킹으로 ping/whitelist skip 후 read_bytes 진입
        from backend.services.file_resolver import mark_path_validated, reset_path_validated
        token = mark_path_validated([str(tmp_path / "x.bin")])
        try:
            with pytest.raises(PermissionError, match="chunking protocol"):
                r.read_bytes(str(tmp_path / "x.bin"))
        finally:
            reset_path_validated(token)
    finally:
        w.close()


# ---------------------------------------------------------------------------
# I3: UNC 화이트리스트 매칭 단위 테스트
# ---------------------------------------------------------------------------
def test_check_allowed_unc_path_matches_unc_prefix(monkeypatch):
    """I3 — `\\\\server\\share\\folder\\file` path와 `\\\\server\\share` prefix 매칭."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    monkeypatch.setattr(file_resolver.sys, "platform", "win32")
    r = CloudiumFileResolver(allowed_prefixes="\\\\corp\\share")
    # 통과 (raise 없음)
    r._check_allowed("\\\\corp\\share\\folder\\file.docx")


def test_check_allowed_unc_path_blocks_different_share(monkeypatch):
    """I3 — 다른 UNC share는 차단."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    monkeypatch.setattr(file_resolver.sys, "platform", "win32")
    r = CloudiumFileResolver(allowed_prefixes="\\\\corp\\public")
    with pytest.raises(PermissionError, match="허용되지 않은 경로"):
        r._check_allowed("\\\\corp\\private\\secret.docx")


# ---------------------------------------------------------------------------
# C-N1: list-of-strings body 우회 차단
# ---------------------------------------------------------------------------
def test_middleware_blocks_list_of_strings_value_under_path_key(monkeypatch, tmp_path):
    """C-N1 회귀 — `{"req_paths": ["//corp/a", "//corp/b"]}` JSON list 형태도 검사.

    부모 key가 PATH_KEYS / MULTI_PATH_KEYS면 list element string도 화이트리스트 검사.
    이 hole이 열려 있으면 D2 정책 단일 출처가 깨짐.
    """
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    allowed = tmp_path / "ok"
    blocked = tmp_path / "block"
    allowed.mkdir()
    blocked.mkdir()
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(allowed)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        # JSON body의 list of strings — 부모 key가 PATH_KEYS면 element도 검사
        r = c.post("/api/anything",
                   json={"req_paths": [str(allowed / "a.docx"), str(blocked / "evil.docx")]})
        assert r.status_code == 403, (
            f"C-N1 회귀: list-of-strings element 검사 누락: {r.status_code} {r.text[:200]}"
        )
        assert r.json().get("code") == "CLOUDIUM_BLOCKED"
    finally:
        set_resolver(LocalFileResolver())


def test_middleware_passes_list_of_strings_when_all_allowed(monkeypatch, tmp_path):
    """C-N1 — 모든 element가 allowed_prefix면 미들웨어 통과."""
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        r = c.post("/api/anything",
                   json={"req_paths": [str(tmp_path / "a"), str(tmp_path / "b")]})
        # 미들웨어 통과 (CLOUDIUM_BLOCKED 아님)
        body = r.json()
        assert body.get("code") != "CLOUDIUM_BLOCKED", (
            f"모두 allowed인데 미들웨어가 차단: {body}"
        )
    finally:
        set_resolver(LocalFileResolver())


# ---------------------------------------------------------------------------
# W-N1: reject_upload_in_cloudium 응답 shape 미들웨어와 통일
# ---------------------------------------------------------------------------
def test_reject_upload_in_cloudium_response_shape_matches_middleware(monkeypatch, tmp_path):
    """W-N1 회귀 — endpoint에서 cloudium upload 거부 시 응답이 `{ok, code, detail}` shape.

    미들웨어 차단 응답과 동일 shape이어야 frontend가 단일 분기로 cloudium 정책
    위반 식별 가능. CloudiumBlockedException + handler 등록의 효과 검증.
    """
    from backend.services.file_resolver import set_resolver, LocalFileResolver, CloudiumFileResolver
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    set_resolver(CloudiumFileResolver(allowed_prefixes=str(tmp_path)))

    try:
        from starlette.testclient import TestClient
        from backend.main import app
        c = TestClient(app, raise_server_exceptions=False)
        c.headers["X-User"] = "test"
        # multipart/form-data로 dummy file 업로드 — UDS template-upload endpoint
        files = {"file": ("template.docx", b"fake-docx-bytes", "application/octet-stream")}
        data = {"job_url": "http://j", "cache_root": str(tmp_path), "build_selector": "lastSuccessfulBuild"}
        r = c.post("/api/jenkins/uds/template-upload", data=data, files=files)
        assert r.status_code == 403, f"upload 차단 안됨: {r.status_code} {r.text[:200]}"
        body = r.json()
        # 미들웨어 차단 응답과 동일 shape
        assert body.get("ok") is False, f"ok=False 누락: {body}"
        assert body.get("code") == "CLOUDIUM_BLOCKED", f"code 필드 누락/오류: {body}"
        assert "detail" in body, f"detail 필드 누락: {body}"
        assert "Cloudium" in body["detail"]
    finally:
        set_resolver(LocalFileResolver())
