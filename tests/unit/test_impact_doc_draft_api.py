"""POST /api/impact/doc-draft — 온디맨드 전체 초안.

job JSON에는 요약(SUTS 10 시퀀스)만 싣고, '전체 보기'를 누를 때만 생성기 기본값(24) 전량을
만든다. 소스가 미해결(cloudium)이면 문서 원문 기준으로 폴백하되 `source`로 근거를 밝힌다.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from backend.routers import impact as impact_router
    app = FastAPI()
    app.include_router(impact_router.router)
    return TestClient(app)


COLS = [f"g_sys_error_his[{i}]" for i in range(3)]


def _job(status: str = "completed", *, with_source: bool = False) -> dict:
    return {
        "job_id": "impact_test_1",
        "status": status,
        "scm_id": "",
        "metadata": {"source_root": "D:/no/such/source" if with_source else ""},
        "result": {
            "change_details": {"s_updateerrorcode": {"after": "void s_updateerrorcode(U8 d)"}},
            "doc_content": {
                "suts": {"s_updateerrorcode": [
                    {"tc_id": "SwUTC_SwUFn_1219", "inputs": {c: "0x0" for c in COLS},
                     "expected": {c: "0x0" for c in COLS},
                     "loc": {"sheet": "2.SW Unit Test Spec", "tc_row": 2103}},
                ]},
                "suts_meta": {"s_updateerrorcode": {
                    "columns": {"inputs": COLS, "expected": COLS, "sheet": "2.SW Unit Test Spec"},
                    "component": "SwCom_07", "test_method": "FNCT", "gen_method": "AEC, ABV",
                    "related_ids": ["SwRS_0101"], "seq_total": 12, "seq_shown": 8,
                }},
                "uds": {"s_updateerrorcode": {"prototype": "void s_updateerrorcode(U16 x)",
                                              "globals": ["[IN] U16 g_sys_error_his"], "calls": []}},
            },
        },
    }


def test_doc_draft_returns_document_grounded_payload(client, monkeypatch):
    """소스 미해결이어도 문서 원문 기준 초안 원재료를 돌려준다(source='document')."""
    import workflow.impact_jobs as jobs
    monkeypatch.setattr(jobs, "load_job", lambda _id: _job())

    r = client.post("/api/impact/doc-draft",
                    json={"job_id": "impact_test_1", "function": "s_updateerrorcode", "doc": "suts"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["source"] == "document"
    # 열 순서(시트 헤더 원문)를 그대로 — TSV 붙여넣기의 권위 소스
    assert body["columns"]["inputs"] == COLS
    # UDS 어노테이션(`[IN] U16 …`)에서 타입 해상 — 배열 첨자는 base로 접힘
    assert body["var_types"]["g_sys_error_his"] == {"type": "uint16_t", "source": "doc_annotation"}
    assert body["meta"]["component"] == "SwCom_07"
    # 문서 축은 doc_total — 생성기 축(gen_total)과 슬롯을 섞지 않는다(deep-review C1)
    assert body["meta"]["doc_total"] == 12 and body["meta"]["doc_shown"] == 8
    assert body["doc_rows"][0]["tc_id"] == "SwUTC_SwUFn_1219"


def test_doc_draft_full_expansion_uses_generator_defaults(client, monkeypatch):
    """소스가 잡히면 생성기 전량(캡 24)을 쓴다 — 카드 요약(10)보다 많이 돌려준다."""
    import backend.routers.impact as router_mod
    import generators.suts as gsuts
    import workflow.impact_jobs as jobs
    import workflow.impact_orchestrator as orch

    monkeypatch.setattr(jobs, "load_job", lambda _id: _job(with_source=True))
    monkeypatch.setattr(orch, "_load_source_sections", lambda _p: {
        "function_details": {"f1": {"name": "s_updateerrorcode", "logic_flow": [], "calls_list": []}},
        "globals_info_map": {},
    })
    monkeypatch.setattr(gsuts, "collect_unit_functions",
                        lambda fdmap, gim=None: [{"name": "s_updateerrorcode",
                                                  "input_vars": [], "output_vars": []}])
    seen: dict = {}

    def _gen(unit, max_seq=6, type_cache=None):
        seen["max_seq"] = max_seq
        return [{"strategy": f"S{i}", "inputs": {"x": i}, "expected": {"r": i}, "description": "d"}
                for i in range(max_seq)]

    monkeypatch.setattr(gsuts, "generate_sequences", _gen)
    monkeypatch.setattr(router_mod, "_logger", router_mod._logger)  # no-op, 명시성

    r = client.post("/api/impact/doc-draft",
                    json={"job_id": "impact_test_1", "function": "s_updateerrorcode", "doc": "suts"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "generator"
    assert seen["max_seq"] == 24, "온디맨드는 생성기 기본값 전량"
    assert len(body["proposal"]) == 24


def test_doc_draft_missing_job_404(client, monkeypatch):
    import workflow.impact_jobs as jobs

    def _raise(_id):
        raise KeyError(_id)

    monkeypatch.setattr(jobs, "load_job", _raise)
    r = client.post("/api/impact/doc-draft", json={"job_id": "nope", "function": "s_foo"})
    assert r.status_code == 404


def test_doc_draft_running_job_409(client, monkeypatch):
    import workflow.impact_jobs as jobs
    monkeypatch.setattr(jobs, "load_job", lambda _id: _job("running"))
    r = client.post("/api/impact/doc-draft", json={"job_id": "x", "function": "s_updateerrorcode"})
    assert r.status_code == 409


@pytest.mark.parametrize(("payload", "code"), [
    ({"job_id": "x", "function": "s_foo", "doc": "vcast"}, 400),   # 미지원 문서
    ({"job_id": "x", "function": "", "doc": "suts"}, 400),          # 함수 누락
])
def test_doc_draft_rejects_bad_input(client, monkeypatch, payload, code):
    import workflow.impact_jobs as jobs
    monkeypatch.setattr(jobs, "load_job", lambda _id: _job())
    assert client.post("/api/impact/doc-draft", json=payload).status_code == code


def test_doc_draft_source_failure_is_surfaced_not_silent(client, monkeypatch):
    """소스 파싱 실패를 조용히 삼키지 않고 warnings로 표면화한다."""
    import workflow.impact_jobs as jobs
    import workflow.impact_orchestrator as orch

    monkeypatch.setattr(jobs, "load_job", lambda _id: _job(with_source=True))

    def _boom(_p):
        raise RuntimeError("parse blew up")

    monkeypatch.setattr(orch, "_load_source_sections", _boom)
    body = client.post("/api/impact/doc-draft",
                       json={"job_id": "x", "function": "s_updateerrorcode", "doc": "suts"}).json()
    assert any("소스 파싱 불가" in w for w in body["warnings"])
    assert body["source"] == "document"      # 문서 폴백으로 계속


def test_doc_draft_reports_failure_when_nothing_could_be_built(client, monkeypatch):
    """소스도 문서도 없으면 ok=False — ok=True로 빈 결과를 주면 프론트가 '불러왔습니다'를
    표시하고 버튼까지 없애 재시도가 막힌다(거짓 성공)."""
    import workflow.impact_jobs as jobs

    empty = _job()
    empty["result"] = {"doc_content": {}, "change_details": {}}
    monkeypatch.setattr(jobs, "load_job", lambda _id: empty)

    body = client.post("/api/impact/doc-draft",
                       json={"job_id": "x", "function": "s_nope", "doc": "suts"}).json()
    assert body["ok"] is False
    assert body["reason"] == "empty_proposal"
    assert any("만들지 못했습니다" in w for w in body["warnings"])


def test_doc_draft_document_path_ok_without_sequences(client, monkeypatch):
    """문서 폴백은 시퀀스를 만들지 않는 게 정상 — meta/columns/var_types가 있으면 ok=True."""
    import workflow.impact_jobs as jobs
    monkeypatch.setattr(jobs, "load_job", lambda _id: _job())

    body = client.post("/api/impact/doc-draft",
                       json={"job_id": "x", "function": "s_updateerrorcode", "doc": "suts"}).json()
    assert body["ok"] is True
    assert body["proposal"] in (None, [], {}), "생성기 없이 시퀀스를 지어내지 않는다"
    assert body["columns"] and body["var_types"]


def test_doc_draft_sits_does_not_return_suts_meta(client, monkeypatch):
    """doc='sits'인데 SUTS 메타/컬럼을 돌려주면 호출부가 **다른 문서의 열 순서**로 TSV를 만든다."""
    import workflow.impact_jobs as jobs
    monkeypatch.setattr(jobs, "load_job", lambda _id: _job())

    body = client.post("/api/impact/doc-draft",
                       json={"job_id": "x", "function": "s_updateerrorcode", "doc": "sits"}).json()
    assert body["meta"] is None
    assert body["columns"] is None
    assert body["doc_rows"] is None


def test_doc_draft_surfaces_source_root_and_registry_drift(client, monkeypatch):
    """어느 소스로 합성했는지 밝히고, job 트리거 소스와 다르면 경고한다(조용히 다른 소스 금지)."""
    import backend.services.scm_registry as reg
    import workflow.impact_jobs as jobs
    import workflow.impact_orchestrator as orch

    monkeypatch.setattr(jobs, "load_job", lambda _id: _job(with_source=True))   # metadata: D:/no/such/source
    monkeypatch.setattr(reg, "get_registry_entry",
                        lambda _sid: type("E", (), {"source_root": "D:/other/source"})())
    monkeypatch.setattr(orch, "_load_source_sections", lambda _p: {})

    body = client.post("/api/impact/doc-draft",
                       json={"job_id": "x", "function": "s_updateerrorcode", "doc": "suts"}).json()
    assert body["source_root"] == "D:/other/source"
    assert any("registry 소스" in w and "다릅니다" in w for w in body["warnings"])


def test_doc_prose_rejects_oversized_deterministic_payload(client):
    """`deterministic`에 크기 상한이 없으면 대용량 body가 그대로 파싱·직렬화된다."""
    huge = {"rows": [{"v": "x" * 1000} for _ in range(400)]}   # ≈400KB
    r = client.post("/api/impact/doc-prose", json={"function": "s_foo", "deterministic": huge})
    assert r.status_code == 422
