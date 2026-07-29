"""Chat 어시스턴트 심층 분석 하드닝 테스트 (2026-06-24).

6렌즈 적대적 분석에서 확정된 결함의 회귀 방지:
- SEC-1 (critical) 경로 confine: report_dir/project_root/oai_config_path/session_id traversal 차단
- SEC-2 (warning) 승인 키워드 단어경계: editor/committed/pushed 오탐 제거, 실제 edit/commit 발동
- SEC-3 (warning) save_pending_approval bool 반환 + 실패 시 승인 게이트 생략(404 방지)
- SEC-4 (warning) approval 게이트 errors 가드(선행 노드 실패 시 pending 미영속)
- SEC-5 (info) report_server _bundle_cache LRU 상한
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest  # noqa: E402  (sys.path 부트스트랩 뒤라 순서가 의도됨)

import backend.services.assistant_service as asvc  # noqa: E402  (sys.path 부트스트랩 뒤라 순서가 의도됨)
import backend.services.chat_approval_store as cas  # noqa: E402  (sys.path 부트스트랩 뒤라 순서가 의도됨)
from backend.mcp.report_server import ReportMCPServer  # noqa: E402  (sys.path 부트스트랩 뒤라 순서가 의도됨)
from backend.services.chat_history_db import (  # noqa: E402  (sys.path 부트스트랩 뒤라 순서가 의도됨)
    init_db,
    reset_engine,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path):
    reset_engine()
    init_db(tmp_path / "test_chat_security_hardening.sqlite")
    yield
    reset_engine()


# ── SEC-1 경로 confine (critical path traversal) ──────────────────────────

class TestPathConfine:
    @pytest.mark.parametrize("evil", [
        "C:/Windows/System32",
        "C:/Users/victim/Documents",
        "/etc/passwd",
        "../../../../etc",
    ])
    def test_confine_rejects_outside_trusted_roots(self, evil):
        assert asvc._confine_path(evil) is None

    def test_confine_allows_reports_subtree(self):
        # DEFAULT_REPORT_DIR 하위는 허용
        out = asvc._confine_path("reports/sessions/abc")
        assert out is not None
        assert "reports" in str(out)

    def test_resolve_report_dir_rejects_absolute_escape(self):
        assert asvc._resolve_report_dir("C:/Windows", None) is None

    def test_resolve_report_dir_blocks_session_traversal(self):
        # session_id 의 ../ traversal 은 base 밖으로 못 나간다
        assert asvc._resolve_report_dir(None, "../../../../etc") is None

    def test_resolve_report_dir_allows_clean_session(self):
        out = asvc._resolve_report_dir(None, "sess1")
        assert out is not None
        assert str(out).endswith(str(Path("reports") / "sessions" / "sess1"))

    def test_safe_project_root_demotes_evil(self):
        out = asvc._safe_project_root({"project_root": "C:/Windows"})
        # 신뢰 기본값(DEFAULT_PROJECT_ROOT, 보통 repo root)으로 강등 — C:/Windows 아님
        assert "Windows" not in out

    def test_safe_project_root_keeps_trusted(self):
        out = asvc._safe_project_root({"project_root": "reports"})
        assert out.endswith("reports")

    def test_confine_oai_config_extra_root(self):
        # 기본 config 디렉토리는 extra_roots 로 허용
        repo_root = Path(asvc.config.__file__).resolve().parent
        out = asvc._confine_path(str(repo_root / "OAI_CONFIG_LIST"), extra_roots=[repo_root])
        assert out is not None


# ── SEC-2 승인 키워드 단어경계 ────────────────────────────────────────────

class TestRiskyTokenWordBoundary:
    @pytest.mark.parametrize("text", [
        "show me the editor layout",     # edit ⊂ editor
        "who got credit for this",        # edit ⊂ credit
        "committed changes overview",     # commit ⊂ committed
        "the pushed branch is stale",     # push ⊂ pushed
        "rewrite was deployed already",   # 단, deploy/write 는 아래 별도
    ])
    def test_no_false_positive_substrings(self, text):
        # "rewrite was deployed already" 는 deploy⊂deployed, write⊂rewrite 둘 다 substring
        # 이므로 단어경계로 제거돼야 한다.
        toks = asvc._match_risky_tokens(text)
        # editor/credit/committed/pushed 는 절대 매칭 금지
        assert "edit" not in toks
        assert "commit" not in toks
        assert "push" not in toks

    @pytest.mark.parametrize("text,expected", [
        ("edit this file", "edit"),
        ("please commit the change", "commit"),
        ("git push now", "push"),
        ("write the config", "write"),
        ("deploy to prod", "deploy"),
    ])
    def test_real_tokens_still_match(self, text, expected):
        assert expected in asvc._match_risky_tokens(text)

    def test_korean_tokens_substring(self):
        assert "커밋" in asvc._match_risky_tokens("커밋해줘")
        assert "배포" in asvc._match_risky_tokens("지금 배포")

    def test_build_approval_request_suppresses_editor(self):
        # "editor" 정보성 질문은 승인 게이트를 띄우지 않는다
        req = asvc._build_approval_request(
            question="show me the editor layout", question_type="code", ui_context=None,
        )
        assert req is None

    def test_build_approval_request_fires_on_real_deploy(self):
        req = asvc._build_approval_request(
            question="deploy to prod now", question_type="general", ui_context=None,
        )
        assert req is not None
        assert req["action_type"] == "publish_report"


# ── SEC-3 save_pending_approval bool 반환 ─────────────────────────────────

class TestSaveReturnsBool:
    def test_save_returns_true_on_success(self):
        ok = cas.save_pending_approval("ap-ok-1", {"owner": "alice", "question": "q"})
        assert ok is True
        assert cas.get_pending_approval("ap-ok-1") is not None

    def test_save_returns_false_on_db_failure(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("db down")
        monkeypatch.setattr(cas, "get_session", _boom)
        ok = cas.save_pending_approval("ap-fail-1", {"owner": "bob"})
        assert ok is False


# ── SEC-3/4 승인 게이트 통합(errors 가드 + save 실패 폴백) ──────────────────

def _fake_cfg():
    return {"model": "m", "api_type": "openai", "api_key": "k", "base_url": "http://x"}


def _answer(question, monkeypatch, *, save_ok=True, cfg=True):
    """LLM/저장을 가짜로 대체해 그래프 흐름만 검증."""
    if cfg:
        monkeypatch.setattr(asvc, "load_oai_config", lambda *a, **k: _fake_cfg())
        monkeypatch.setattr(asvc, "load_oai_configs", lambda *a, **k: [_fake_cfg()])
    else:
        monkeypatch.setattr(asvc, "load_oai_config", lambda *a, **k: None)
        monkeypatch.setattr(asvc, "load_oai_configs", lambda *a, **k: [])
    monkeypatch.setattr(asvc, "save_pending_approval", lambda *a, **k: save_ok)
    monkeypatch.setattr(
        asvc, "_run_llm_candidates",
        lambda **k: ("LLM 정상 답변", _fake_cfg(), "", 1.0),
    )
    return asvc.answer_chat(
        mode="local", question=question, report_dir=None, session_id=None,
        llm_model=None, oai_config_path=None, ui_context={"current_view": "detail"},
        history=None, requester="alice",
    )


class TestApprovalGateIntegration:
    def test_gate_fires_when_save_succeeds(self, monkeypatch):
        res = _answer("배포해줘", monkeypatch, save_ok=True)
        assert res["approval_required"] is True
        assert res["approval_request"] is not None

    def test_gate_skipped_when_save_fails(self, monkeypatch):
        # SEC-3: save 실패 시 승인 카드 대신 일반 답변으로 폴백(404 방지)
        res = _answer("배포해줘", monkeypatch, save_ok=False)
        assert res["approval_required"] is False
        assert res["approval_request"] is None
        assert "LLM 정상 답변" in res["answer"]

    def test_gate_skipped_when_prior_node_errors(self, monkeypatch):
        # SEC-4: select_model errors(LLM config 부재) 시 위험 질문이어도 pending 미영속
        res = _answer("배포해줘", monkeypatch, cfg=False)
        assert res["approval_required"] is False
        assert res["approval_request"] is None


# ── SEC-5 report_server _bundle_cache LRU 상한 ────────────────────────────

class TestReportBundleCacheLRU:
    def test_cache_bounded(self, tmp_path):
        srv = ReportMCPServer()
        srv.clear_cache()
        for i in range(ReportMCPServer._CACHE_MAX + 20):
            srv.read_bundle(tmp_path / f"d{i}")
        assert len(ReportMCPServer._bundle_cache) <= ReportMCPServer._CACHE_MAX
        srv.clear_cache()

    def test_read_bundle_returns_copy(self, tmp_path):
        # 반환 객체는 최상위 얕은복사라 호출자 변이가 캐시를 오염시키지 않는다
        srv = ReportMCPServer()
        srv.clear_cache()
        d = tmp_path / "bundle_dir"
        d.mkdir()
        b1 = srv.read_bundle(d)
        b1["__injected__"] = "evil"
        b2 = srv.read_bundle(d)
        assert "__injected__" not in b2
        srv.clear_cache()


# ── R1 oai_config_path 서버 고정 (SSRF-lite 차단) ─────────────────────────

class TestOaiConfigServerFixed:
    def test_client_oai_config_path_ignored(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(asvc, "load_oai_config", lambda p: (captured.update(path=p) or _fake_cfg()))
        monkeypatch.setattr(asvc, "load_oai_configs", lambda *a, **k: [_fake_cfg()])
        monkeypatch.setattr(asvc, "_run_llm_candidates", lambda **k: ("ok", _fake_cfg(), "", 1.0))
        asvc.answer_chat(
            mode="local", question="안녕", report_dir=None, session_id=None, llm_model=None,
            oai_config_path="C:/evil/secret.json", ui_context={"current_view": "detail"},
            history=None, requester="alice",
        )
        # 클라이언트가 보낸 임의 경로가 무시되고 서버 고정값(DEFAULT)이 쓰임
        assert captured.get("path") != "C:/evil/secret.json"


# ── R2 부정문 승인 억제 + _skipped 노드 ───────────────────────────────────

class TestNegationSuppression:
    @pytest.mark.parametrize("text", [
        "커밋하지마", "푸시하지 말고 보여줘", "don't commit this", "deploy without pushing",
    ])
    def test_negation_suppresses_gate(self, text):
        assert asvc._build_approval_request(
            question=text, question_type="general", ui_context=None,
        ) is None

    def test_has_negation(self):
        assert asvc._has_negation("커밋하지마")
        assert asvc._has_negation("don't commit")
        assert not asvc._has_negation("커밋해줘")

    def test_real_action_still_gates(self):
        # 부정문 아닌 실제 실행 요청은 여전히 게이트
        assert asvc._build_approval_request(
            question="deploy to prod now", question_type="general", ui_context=None,
        ) is not None


class TestSkippedNodeEvent:
    def test_skipped_emits_skipped_and_not_leak(self):
        from workflow.chat_graph import new_chat_graph_state, run_chat_graph
        events = []
        state = new_chat_graph_state(
            mode="local", question="q", session_id=None, report_dir=None,
            ui_context=None, history=None,
        )
        run_chat_graph(
            initial_state=state,
            nodes=[("a", lambda s: {"approval_required": True}), ("b", lambda s: {"_skipped": True})],
            event_callback=events.append,
        )
        fin_b = [e for e in events if e["type"] == "graph_node_finished" and e["payload"]["node"] == "b"]
        assert fin_b and fin_b[0]["payload"]["skipped"] is True
        # 정상 노드는 skipped=False
        fin_a = [e for e in events if e["type"] == "graph_node_finished" and e["payload"]["node"] == "a"]
        assert fin_a and fin_a[0]["payload"]["skipped"] is False
        # _skipped 센티널이 state 로 새지 않음
        assert "_skipped" not in state.extra
        assert not hasattr(state, "_skipped")
