"""워커 생존은 **경로와 무관한 사실**이다 (R42 N8).

예전 게이트는 입력 dict 의 첫 항목 하나를 찔러 보고 그 예외 문구가 "worker" 로 갈릴 때만
"Cloudium worker 를 실행하세요" 행을 냈다. 그래서 첫 입력이 허용 prefix 밖이거나(예외가
prefix 로 갈린다) 입력이 아예 없으면, 워커가 죽어 있어도 화면엔 **입력이 없다**고만 나왔다.
사용자는 파일을 다시 고르러 갔다 — 실제로는 워커를 켜면 끝나는 일이었다.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import file_resolver as fr

client = TestClient(app)
HEADERS = {"X-User": "tester"}


class _FakeCloudium:
    """cloudium resolver 흉내 — 모든 경로가 **허용 prefix 밖**이라 prefix 예외를 낸다."""

    mode = "cloudium"
    worker_host = "127.0.0.1"
    worker_port = 65123
    gate_process = "excel_rename_gui_v2.exe"

    def exists(self, path: str) -> bool:
        raise PermissionError("허용되지 않은 경로 접근 차단됨: " + str(path))

    def is_dir(self, path: str) -> bool:
        raise PermissionError("허용되지 않은 경로 접근 차단됨: " + str(path))


def _preflight(monkeypatch, *, alive: bool, resolver=None, payload=None) -> dict:
    res = resolver if resolver is not None else _FakeCloudium()
    monkeypatch.setattr(fr, "get_resolver", lambda: res)
    monkeypatch.setattr(fr, "is_gate_running", lambda **_kw: alive)
    body = payload if payload is not None else {
        "doc_type": "uds",
        "doc_paths": {"srs": r"U:\somewhere\SRS.docx"},
    }
    r = client.post("/api/docgen/preflight", json=body, headers=HEADERS)
    assert r.status_code == 200, r.text
    return r.json()


def _worker_step(data: dict):
    return next((s for s in data["steps"] if s["id"] == "worker"), None)


def test_dead_worker_is_reported_even_when_first_input_is_outside_prefix(monkeypatch) -> None:
    """첫 입력이 prefix 밖이어도 워커가 죽었으면 안내가 뜬다 — 이게 옛 결함의 본체다."""
    step = _worker_step(_preflight(monkeypatch, alive=False))
    assert step is not None, "워커가 죽었는데 접근 행이 없다"
    assert step["state"] == "error"
    assert "worker" in step["reason"].lower()
    assert any(a.get("kind") == "run_worker" for a in (step.get("actions") or []))


def test_dead_worker_is_reported_when_there_are_no_inputs_at_all(monkeypatch) -> None:
    """입력이 하나도 없으면 예전엔 접근 점검 자체를 건너뛰었다."""
    data = _preflight(monkeypatch, alive=False, payload={"doc_type": "uds"})
    step = _worker_step(data)
    assert step is not None and step["state"] == "error"


def test_live_worker_adds_no_row(monkeypatch) -> None:
    """살아 있으면 조용하다 — 멀쩡한 워커에 '실행하세요' 를 띄우지 않는다."""
    assert _worker_step(_preflight(monkeypatch, alive=True)) is None


def test_unknown_endpoint_is_unmeasured_not_alive(monkeypatch) -> None:
    """엔드포인트를 모르면 '살아 있다' 가 아니라 **못 쟀다** 다(미측정 ≠ 통과)."""

    class _NoEndpoint(_FakeCloudium):
        worker_host = ""
        worker_port = None

    def _boom(**_kw):
        raise AssertionError("엔드포인트를 모르는데 ping 을 시도했다")

    monkeypatch.setattr(fr, "is_gate_running", _boom)
    monkeypatch.setattr(fr, "get_resolver", lambda: _NoEndpoint())
    r = client.post("/api/docgen/preflight",
                    json={"doc_type": "uds", "doc_paths": {"srs": r"U:\x\SRS.docx"}},
                    headers=HEADERS)
    assert r.status_code == 200, r.text
    step = _worker_step(r.json())
    assert step is not None and step["state"] == "unmeasured"


def test_ping_failure_is_unmeasured_not_dead(monkeypatch) -> None:
    """확인 자체가 실패하면 '죽었다' 로 단정하지 않는다."""

    def _raise(**_kw):
        raise OSError("socket exploded")

    monkeypatch.setattr(fr, "is_gate_running", _raise)
    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeCloudium())
    r = client.post("/api/docgen/preflight",
                    json={"doc_type": "uds", "doc_paths": {"srs": r"U:\x\SRS.docx"}},
                    headers=HEADERS)
    assert r.status_code == 200, r.text
    step = _worker_step(r.json())
    assert step is not None and step["state"] == "unmeasured"


def test_local_mode_never_probes_the_worker(monkeypatch) -> None:
    """로컬 모드에선 워커 판정을 하지 않는다(있지도 않은 것을 물으면 거짓 경고)."""

    class _Local:
        mode = "local"

        def exists(self, path: str) -> bool:
            return False

        def is_dir(self, path: str) -> bool:
            return False

    def _boom(**_kw):
        raise AssertionError("local 모드에서 워커를 찔렀다")

    monkeypatch.setattr(fr, "is_gate_running", _boom)
    monkeypatch.setattr(fr, "get_resolver", lambda: _Local())
    r = client.post("/api/docgen/preflight",
                    json={"doc_type": "uds", "doc_paths": {"srs": r"C:\x\SRS.docx"}},
                    headers=HEADERS)
    assert r.status_code == 200, r.text
    assert _worker_step(r.json()) is None


def test_worker_error_on_an_input_row_still_offers_a_way_out(monkeypatch) -> None:
    """(리뷰 W3) ping 은 pong 인데 **이 read 가** 워커 연결 실패로 죽는 창이 있다.

    생존 판정은 1초 TTL 캐시라, 그 사이 워커가 죽으면 접근 행은 안 뜨고 입력 행만 오류가
    된다. 그때 조치가 없으면 사용자는 "접근 거부" 문장만 보고 무엇을 눌러야 할지 모른다.
    """

    class _WorkerDiesMidRead(_FakeCloudium):
        def exists(self, path: str) -> bool:
            raise PermissionError(
                "Cloudium worker 연결 실패 (127.0.0.1:65123): [WinError 10061]")

    data = _preflight(monkeypatch, alive=True, resolver=_WorkerDiesMidRead())
    rows = [s for s in data["steps"] if s.get("phase") == "input" and s["state"] == "error"]
    assert rows, "워커 오류로 죽은 입력 행이 없다"
    for row in rows:
        acts = [a.get("kind") for a in (row.get("actions") or [])]
        assert "run_worker" in acts, f"조치 없는 워커 오류 행: {row}"


def test_prefix_error_still_points_at_registration_not_the_worker(monkeypatch) -> None:
    """대조군 — prefix 밖은 워커 문제가 아니다. 두 사유에 같은 버튼을 달면 구별이 사라진다."""
    data = _preflight(monkeypatch, alive=True)
    rows = [s for s in data["steps"] if s.get("phase") == "input" and s["state"] == "error"]
    assert rows
    for row in rows:
        acts = [a.get("kind") for a in (row.get("actions") or [])]
        assert "open_scm" in acts and "run_worker" not in acts, row
