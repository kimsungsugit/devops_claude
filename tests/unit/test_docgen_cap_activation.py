"""게이트에서 고른 상한·선택지가 **실제로 산출물을 바꾸는가**.

## 왜 이 파일인가

`test_docgen_cap_wiring_parity.py` 는 세 표(공시 / 핸들러 Form / 프론트 전송)가 서로
맞는지를 본다. 그건 **이름**의 정합이다. 이름이 다 맞아도 값이 생성기까지 안 내려가면
결과는 같다 — 사용자는 고쳤다고 믿고 문서는 그대로다.

실측으로 그런 것이 셋 있었다:

| 값 | 증상 |
|---|---|
| UDS `reference_doc_path` | 프론트가 보내는데 핸들러가 **선언하지 않아** FastAPI 가 조용히 버렸다. 그동안 게이트는 "정본을 템플릿으로 씁니다 / 표준 템플릿은 쓰이지 않습니다" 라고 **반대말**을 공시했다 |
| `/api/code/*` 의 `max_files` | 질의 파라미터로 받아 **캐시 서명 계산에만** 쓰고 파싱에는 안 넘겼다 |
| STS `max_steps_per_tc` | 생성기 3곳이 모듈 상수를 직참조해 요청으로는 바꿀 수 없었다 |

그래서 여기서는 **값이 끝까지 가는가**를 잰다.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

from backend.routers import docgen_preflight as pf
from backend.services import docgen_requirements as req
from backend.services.docgen_template_source import (
    TEMPLATE_SOURCE_CHOICES,
    TEMPLATE_SOURCE_REFERENCE,
    TEMPLATE_SOURCE_STANDARD,
    choose_template_source,
    prefer_reference_from,
)

_REPO = Path(__file__).resolve().parents[2]


# ── 템플릿 출처 ────────────────────────────────────────────────────────────

class TestTemplateSourceSwitch:
    """어느 파일을 템플릿으로 쓰는지는 **문서의 나머지 전부**를 정한다."""

    def test_only_standard_turns_off_reference_first(self) -> None:
        assert prefer_reference_from(TEMPLATE_SOURCE_STANDARD) is False
        assert prefer_reference_from(TEMPLATE_SOURCE_REFERENCE) is True
        # 미설정은 **서버 기본**(정본 우선)이다 — 여기서 기본값이 뒤집히면 저장 칸을
        # 비웠을 때 조용히 다른 문서가 나온다.
        assert prefer_reference_from("") is True
        assert prefer_reference_from(None) is True

    def test_unknown_token_falls_back_to_the_default_not_the_other_side(self) -> None:
        """오타가 **반대 동작**이 되면 안 된다.

        `_suts_normalize_scope` 가 같은 이유로 생성기 정의를 되쓴다 — 예전에 게이트와
        생성기가 여집합을 봐서 `sud` 하나에 두 화면이 반대말을 했다.
        """
        assert prefer_reference_from("standrad") is True   # 오타
        assert prefer_reference_from("STANDARD") is False  # 대소문자는 흡수한다

    def test_the_switch_actually_changes_the_chosen_file(self) -> None:
        got_ref, _ = choose_template_source(
            "uds", registered_template="T.docx", reference_doc="R.docx",
            prefer_reference=prefer_reference_from(""))
        got_std, _ = choose_template_source(
            "uds", registered_template="T.docx", reference_doc="R.docx",
            prefer_reference=prefer_reference_from(TEMPLATE_SOURCE_STANDARD))
        assert (got_ref, got_std) == ("R.docx", "T.docx")

    @pytest.mark.parametrize("doc_type", ["uds", "sts", "suts", "sits"])
    def test_every_gate_doc_offers_the_switch(self, doc_type: str) -> None:
        ch = (req.requirements_for(doc_type).get("choices") or {}).get("template_source")
        assert ch, f"{doc_type}: 템플릿 출처 선택지가 없다"
        assert {o["value"] for o in ch["options"]} <= set(TEMPLATE_SOURCE_CHOICES)


class TestUdsHandlerHonoursTheReferenceDoc:
    """UDS 핸들러가 정본을 **받고 쓰는가** — 게이트 문장의 진위가 여기 달렸다."""

    @pytest.mark.parametrize("handler", [
        "POST /api/jenkins/uds/generate-async",
        "POST /api/jenkins/uds/generate",
    ])
    def test_declares_reference_doc_path(self, handler: str) -> None:
        from backend.main import app
        for route in app.routes:
            for method in getattr(route, "methods", None) or ():
                if f"{method} {route.path}" != handler:
                    continue
                params = inspect.signature(route.endpoint).parameters
                # 선언이 없으면 FastAPI 가 **조용히** 버린다 — 예외도 로그도 없다.
                assert "reference_doc_path" in params, f"{handler}: 정본을 안 받는다"
                assert "template_source" in params, f"{handler}: 출처 선택을 안 받는다"
                return
        raise AssertionError(f"{handler}: 그런 라우트가 없다")

    @pytest.mark.parametrize("rel,token", [
        ("backend/routers/jenkins.py", '"uds", registered_template=template_path'),
        ("backend/routers/local.py", '"sits", registered_template=template_path'),
    ])
    def test_handlers_delegate_to_the_single_rule(self, rel: str, token: str) -> None:
        """규칙을 핸들러가 복제하지 않는다 — 복제하면 4곳이 서로 다르게 진화한다."""
        src = (_REPO / rel).read_text(encoding="utf-8")
        assert token in src, f"{rel}: {token!r} 위임이 사라졌다"

    def test_uds_passes_the_resolved_template_not_the_registered_one(self) -> None:
        """해석 결과를 넘겨야 한다.

        원문 `template_path` 를 그대로 넘기면 선택은 계산만 되고 **버려진다** —
        게이트는 정본을 이름 대고 생성기는 표준 템플릿을 연다.
        """
        src = (_REPO / "backend/routers/jenkins.py").read_text(encoding="utf-8")
        assert 'template_path=_uds_tpl or ""' in src, "비동기 판이 해석 결과를 안 넘긴다"
        assert 'tpl = str(_uds_tpl or "").strip() or None' in src, "동기 판이 안 넘긴다"


# ── 상한이 생성기까지 가는가 ────────────────────────────────────────────────

class TestUdsCapsReachTheGenerator:
    def test_generator_accepts_caps_and_falls_back_to_config(self) -> None:
        from report_gen.uds_generator import generate_uds_source_sections
        params = inspect.signature(generate_uds_source_sections).parameters
        for name in ("max_files", "max_items"):
            assert name in params, f"{name} 를 안 받는다"
            # 기본값은 `None` — 숫자를 여기 복제하면 `config`(환경변수로 덮임)와 갈린다.
            assert params[name].default is None, f"{name} 기본값이 숫자로 굳어 있다"

    def test_cache_key_separates_different_caps(self) -> None:
        """상한이 키에 없으면 값을 올려도 **옛 상한으로 만든 payload** 가 돌아온다."""
        from backend.helpers.uds import _source_sections_disk_cache_path as p
        a = p("C:/src", True, 1200, 120)
        assert p("C:/src", True, 300, 120) != a, "max_files 가 키에 없다"
        assert p("C:/src", True, 1200, 40) != a, "max_items 가 키에 없다"
        assert p("C:/src", True, 1200, 120) == a, "같은 입력인데 키가 달라졌다"

    def test_cached_reader_declares_the_caps(self) -> None:
        from backend.helpers.uds import _get_source_sections_cached
        params = inspect.signature(_get_source_sections_cached).parameters
        assert {"max_files", "max_items"} <= set(params)
        # 예전엔 `max_files: int = 1200` 이라 `DEVOPS_UDS_MAX_FILES=77` 이어도
        # 서명은 1200개로 계산돼 어긋났다.
        assert params["max_files"].default is None

    def test_file_cap_actually_limits_the_scan(self, tmp_path: Path) -> None:
        """행동 축 — 상한을 낮추면 **읽는 파일이 실제로 줄어야** 한다."""
        from report_gen.uds_generator import generate_uds_source_sections
        for i in range(6):
            (tmp_path / f"m{i}.c").write_text(
                f"int fn_{i}(int a) {{ return a + {i}; }}\n", encoding="utf-8")
        full = generate_uds_source_sections(str(tmp_path), preprocess=False)
        few = generate_uds_source_sections(str(tmp_path), preprocess=False, max_files=2)
        assert int((full.get("file_scan") or {}).get("scanned") or 0) == 6
        assert int((few.get("file_scan") or {}).get("scanned") or 0) == 2
        assert (few.get("file_scan") or {}).get("truncated") is True
        assert (full.get("file_scan") or {}).get("truncated") is False


class TestStsStepCapReachesEveryGenerator:
    """스텝 상한을 세 경로가 **같이** 받아야 한다 — 한 곳만 놓치면 같은 문서 안에서
    TC 마다 상한이 달라진다."""

    @pytest.mark.parametrize("fn_name", [
        "_generate_steps_from_flow", "_generate_review_steps", "_parse_sts_ai_response",
        "enhance_test_cases_with_ai",
    ])
    def test_takes_max_steps(self, fn_name: str) -> None:
        from generators import sts
        params = inspect.signature(getattr(sts, fn_name)).parameters
        assert "max_steps" in params, f"{fn_name}: 스텝 상한을 안 받는다"
        assert params["max_steps"].default == sts._MAX_STEPS_PER_TC, (
            f"{fn_name}: 기본값이 모듈 상수와 다르다")

    def test_review_steps_obey_the_cap(self) -> None:
        from generators.sts import _generate_review_steps
        r = {"id": "SRS-1", "title": "t", "description": "d" * 40,
             "software_state": "RUN"}
        assert len(_generate_review_steps(r, max_steps=2)[0]) <= 2
        # 상한을 올리면 실제로 더 담긴다 — "항상 2개" 를 통과시키지 않는다.
        assert len(_generate_review_steps(r, max_steps=99)[0]) > 2

    def test_ai_payload_obeys_the_cap(self) -> None:
        import json

        from generators.sts import _parse_sts_ai_response
        steps = [{"action": f"a{i}", "expected": f"e{i}"} for i in range(20)]
        reply = json.dumps({"steps": steps})
        assert len(_parse_sts_ai_response(reply, max_steps=3)["steps"]) == 3
        assert len(_parse_sts_ai_response(reply, max_steps=18)["steps"]) == 18

    def test_config_carries_it_from_the_handler(self) -> None:
        """`project_config` 경로가 `max_tc_per_req` 와 같아야 한다 — 다른 경로를 만들면
        한쪽만 배선된 채로 남는다."""
        src = (_REPO / "generators/sts.py").read_text(encoding="utf-8")
        assert 'config.get("max_steps_per_tc")' in src
        router = (_REPO / "backend/routers/jenkins.py").read_text(encoding="utf-8")
        assert '"max_steps_per_tc": max_steps_per_tc,' in router


# ── 전량 축과 절단 축은 서로 다른 말이다 ───────────────────────────────────

class TestCapMeasurementLadders:
    def test_full_total_distinguishes_no_axis_from_not_measured(self) -> None:
        """`_NO_MEASURE`(영영 못 잼)와 `None`(아직 안 잼)을 접으면 안 된다.

        접는 방향마다 결함이 다르다 — 앞으로 접으면 verdict 가 `unknown` 에 고착되고,
        뒤로 접으면 곧 나올 손실을 "측정하지 않습니다" 로 덮는다.
        """
        cap = req.requirements_for("sits")["caps"]["max_flows"]
        assert pf._cap_full_total("max_flows", cap, {}) is None
        assert pf._cap_full_total("max_flows", cap, {"sits": {"flows_total": 145}}) == {
            "value": 145, "basis": pf._SUG_MEASURED}
        steps_cap = req.requirements_for("sts")["caps"]["max_steps_per_tc"]
        assert pf._cap_full_total("max_steps_per_tc", steps_cap, {}) is pf._NO_MEASURE

    def test_suggestion_is_never_invented_for_the_file_scan(self) -> None:
        """스캔은 상한에 닿는 즉시 멈춰 **전체 파일 수를 모른다**.

        모르는 수를 "전부 N" 으로 제안하면 사용자는 그 값을 넣고 다 담겼다고 믿는다.
        """
        tm = {"uds_file_scan": {"measured": True, "cap": 1200,
                                "scanned": 1200, "truncated": True}}
        assert pf._cap_suggested_from_truncation("max_source_files", tm) is None

    def test_category_suggestion_is_the_largest_category(self) -> None:
        """상한은 **분류마다** 걸린다 — 합계로 제안하면 필요보다 훨씬 큰 수가 나온다."""
        tm = {"uds_category_caps": {"measured": True, "cap": 120, "truncated": {
            "macros": {"total": 3881, "cap": 120, "dropped": 3761},
            "type_defs": {"total": 130, "cap": 120, "dropped": 10}}}}
        assert pf._cap_suggested_from_truncation("max_items_per_category", tm) == 3881

    def test_measured_at_reports_the_cap_the_numbers_came_from(self) -> None:
        tm = {"uds_category_caps": {"measured": True, "cap": 120, "truncated": {}}}
        assert pf._cap_measured_at("max_items_per_category", tm) == 120
        assert pf._cap_measured_at("max_flows", tm) is None


# ── 핸들러를 실제로 통과시키는 축 ───────────────────────────────────────────

class TestUdsHandlerPassesTheChoiceThrough:
    """구조 검사는 배선의 **존재**만 본다. 값이 끝까지 가는지는 돌려 봐야 안다.

    이 결함의 실체가 정확히 그것이었다 — 프론트는 `reference_doc_path` 를 보내고 있었고
    핸들러가 선언하지 않아 FastAPI 가 **조용히** 버렸다. 예외도 로그도 없었고, 게이트만
    "정본을 씁니다" 라고 말했다.
    """

    def _call(self, tmp_path, monkeypatch, **form):
        import threading

        from fastapi.testclient import TestClient

        from backend.main import app
        from backend.routers import jenkins as jk

        seen = {}
        done = threading.Event()

        def _fake(**kwargs):
            seen.update(kwargs)
            done.set()
            return {"ok": True, "filename": "x.docx"}

        monkeypatch.setattr(jk, "_uds_generate_from_paths", _fake)
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.c").write_text("int f(void){return 0;}", encoding="utf-8")
        srs = tmp_path / "srs.docx"
        srs.write_text("x", encoding="utf-8")

        body = {"job_url": "http://ci/job/x/", "source_root": str(src),
                "req_paths": str(srs), **form}
        r = TestClient(app).post("/api/jenkins/uds/generate-async", data=body,
                                 headers={"X-User": "tester"})
        assert r.status_code == 200, r.text
        assert done.wait(20), "생성 워커가 시작되지 않았다"
        return seen

    def test_reference_doc_becomes_the_template_by_default(self, tmp_path, monkeypatch):
        ref = tmp_path / "SUDS_v1.02.docx"
        ref.write_text("ref", encoding="utf-8")
        tpl = tmp_path / "std.docx"
        tpl.write_text("tpl", encoding="utf-8")
        seen = self._call(tmp_path, monkeypatch,
                          reference_doc_path=str(ref), template_path=str(tpl))
        assert seen["template_path"] == str(ref), (
            "정본이 버려졌다 — 게이트는 '정본을 씁니다' 라고 말하는데 실제는 반대다")

    def test_standard_choice_flips_it(self, tmp_path, monkeypatch):
        ref = tmp_path / "SUDS_v1.02.docx"
        ref.write_text("ref", encoding="utf-8")
        tpl = tmp_path / "std.docx"
        tpl.write_text("tpl", encoding="utf-8")
        seen = self._call(tmp_path, monkeypatch, reference_doc_path=str(ref),
                          template_path=str(tpl), template_source="standard")
        assert seen["template_path"] == str(tpl), "선택이 산출물 경로를 바꾸지 못한다"

    def test_caps_reach_the_generator_call(self, tmp_path, monkeypatch):
        seen = self._call(tmp_path, monkeypatch,
                          max_source_files="2000", max_items_per_category="500")
        assert seen["max_source_files"] == 2000
        assert seen["max_items_per_category"] == 500

    def test_unset_caps_stay_none_so_config_decides(self, tmp_path, monkeypatch):
        seen = self._call(tmp_path, monkeypatch)
        assert seen["max_source_files"] is None
        assert seen["max_items_per_category"] is None


# ── 뮤테이션이 드러낸 공백 (2026-08-31) ─────────────────────────────────────

class TestCapsSurviveTheCacheLayer:
    """라이브 경로는 **캐시 조회를 거친다**.

    생성기를 직접 부르는 검증만 있으면, 캐시 조회가 상한을 안 넘겨도 초록이다
    (뮤턴트 M71 이 그렇게 살아남았다). 실제 UDS 생성은 이 함수를 지난다.
    """

    def _src(self, tmp_path, n=6):
        d = tmp_path / "src"
        d.mkdir()
        for i in range(n):
            (d / f"m{i}.c").write_text(f"int fn_{i}(void) {{ return {i}; }}\n",
                                       encoding="utf-8")
        return d

    def test_cache_reader_passes_the_cap_to_the_parser(self, tmp_path, monkeypatch):
        from backend.helpers import uds as uds_mod
        # 디스크 캐시를 임시 경로로 돌린다 — 저장소 캐시를 테스트가 오염시키지 않게.
        monkeypatch.setattr(uds_mod, "_source_sections_disk_cache_path",
                            lambda *a, **k: tmp_path / "disk.json")
        src = self._src(tmp_path)
        got = uds_mod._get_source_sections_cached(str(src), max_files=2, preprocess=False)
        assert int((got.get("file_scan") or {}).get("scanned") or 0) == 2, (
            "캐시 조회가 상한을 파싱에 안 넘긴다 — 값을 올려도 문서가 안 바뀐다")
        assert (got.get("file_scan") or {}).get("truncated") is True

    def test_different_caps_do_not_share_a_cache_entry(self, tmp_path, monkeypatch):
        """키가 상한을 안 담으면 두 번째 호출이 **첫 상한으로 만든 payload** 를 받는다."""
        from backend.helpers import uds as uds_mod
        monkeypatch.setattr(uds_mod, "_source_sections_disk_cache_path",
                            lambda *a, **k: tmp_path / "disk.json")
        src = self._src(tmp_path)
        few = uds_mod._get_source_sections_cached(str(src), max_files=2, preprocess=False)
        many = uds_mod._get_source_sections_cached(str(src), max_files=6, preprocess=False)
        assert (few["file_scan"]["scanned"], many["file_scan"]["scanned"]) == (2, 6)


def test_ai_enhancement_forwards_the_step_cap(monkeypatch):
    """받는 것과 **넘기는 것**은 다르다.

    두 함수가 `max_steps` 를 선언만 하고 사이에서 안 넘기면, AI 보강분만 모듈 상수로
    잘려 같은 문서 안에서 TC 마다 스텝 상한이 달라진다(뮤턴트 M73).
    """
    import json

    from generators import sts

    monkeypatch.setattr(sts, "_sts_ai_call_with_retry", lambda *a, **k: json.dumps({
        "steps": [{"action": f"a{i}", "expected": f"e{i}"} for i in range(20)],
    }))
    monkeypatch.setitem(sys.modules, "workflow.ai",
                        type(sys)("workflow.ai"))
    sys.modules["workflow.ai"].agent_call = lambda *a, **k: ""

    tc = {"srs_id": "SRS-1", "title": "t", "steps": [{"action": "f()", "expected": "e"}]}
    sts.enhance_test_cases_with_ai([tc], {}, {"model": "x"}, max_steps=3)
    assert len(tc["steps"]) == 3, "AI 보강 스텝이 호출자 상한을 안 받는다"


def test_file_scan_gets_no_suggestion_even_when_categories_have_one():
    """두 축이 **함께 있을 때**를 재야 한다.

    분류 절단만 있는 픽스처로는 파일 스캔 축이 어차피 `None` 이라 뮤턴트가 살아남는다.
    실제로는 한 번 측정하면 두 축이 같이 채워진다.
    """
    tm = {
        "uds_file_scan": {"measured": True, "cap": 1200, "scanned": 1200,
                          "truncated": True},
        "uds_category_caps": {"measured": True, "cap": 120, "truncated": {
            "macros": {"total": 3881, "cap": 120, "dropped": 3761}}},
    }
    # 스캔은 상한에 닿는 즉시 멈춰 **전체 파일 수를 모른다** — 옆 축의 수를 빌려 오면
    # 사용자는 그 값을 넣고 "이제 다 담긴다" 고 믿는다.
    assert pf._cap_suggested_from_truncation("max_source_files", tm) is None
    assert pf._cap_suggested_from_truncation("max_items_per_category", tm) == 3881


# ── `max_tc_per_req` 의 두 번째 축 ─────────────────────────────────────────

class TestTcCapReachesThePerFunctionAxis:
    """상한 이름은 `요구당` 인데 **함수당**이 더 세게 걸리던 자리.

    `generate_test_cases` 는 `config` 에서 상한을 읽어 함수 루프를 끊는다(이 축은 오래
    정상이었다). 그런데 `_generate_steps_from_flow` 가 마지막에
    `test_cases[:_MAX_TC_PER_REQ]` 로 **모듈 상수**를 직참조해서, 함수 하나에 매핑된
    요구는 상한을 아무리 올려도 5 에서 멈췄다. `max_steps_per_tc` 가 라운드 7 전에
    있던 자리와 같은 형태다.
    """

    @staticmethod
    def _switch_flow(n_cases: int):
        """분기 n 개짜리 switch — 함수 하나로 TC 를 n 개 만들 수 있는 최소 재료."""
        return [{
            "type": "switch",
            "expr": "mode",
            "cases": [{"label": f"CASE_{i}", "body": [f"handler_{i}"]} for i in range(n_cases)],
            "default_calls": [],
        }]

    def test_one_function_can_exceed_the_module_constant(self):
        from generators import sts

        flow = self._switch_flow(12)
        info = {"name": "fn_switch", "params": [], "return_type": "void"}
        got = sts._generate_steps_from_flow(flow, info, max_tc=12)
        assert len(got) == 12, (
            f"함수 하나가 낸 TC 가 {len(got)}개 — 모듈 상수 5 에 걸려 있다. "
            "사용자가 상한을 올려도 산출이 안 늘어난다")

    def test_the_default_is_unchanged(self):
        """기본값에서는 예전과 똑같아야 한다 — 이 fix 는 상한을 **올릴 때만** 달라진다."""
        from generators import sts

        flow = self._switch_flow(12)
        info = {"name": "fn_switch", "params": [], "return_type": "void"}
        assert len(sts._generate_steps_from_flow(flow, info)) == sts._MAX_TC_PER_REQ

    def test_generate_test_cases_carries_the_config_value_all_the_way_down(self):
        """end-to-end: 요구 1개 · 함수 1개 · 분기 12개.

        바깥 루프만 고쳐져 있으면 여기서 5 가 나온다(함수가 하나뿐이라 루프가 끊길
        일이 없고, 안쪽 상수가 유일한 제약이 된다).
        """
        from generators import sts

        req_row = {"id": "SRS-001", "title": "모드 처리", "req_type": "기능"}
        details = {"F1": {"name": "fn_switch", "params": [], "return_type": "void",
                          "logic_flow": self._switch_flow(12)}}
        tcs = sts.generate_test_cases(
            [req_row], details, {"SRS-001": ["F1"]},
            project_config={"max_tc_per_req": 12},
        )
        assert len(tcs) == 12, f"{len(tcs)}개 — config 값이 안쪽 축까지 안 내려간다"

    @staticmethod
    def _sibling_ifs(n: int):
        """형제 `if` n 개 — 각각 참/거짓 두 갈래라 TC 재료가 2n 개 생긴다.

        ⚠ switch 로는 이 시험이 안 된다. switch 는 `cases[:max_tc]` 가 **먼저** 자르므로
          마지막 슬라이스를 지워도 개수가 같아, "상한을 아예 안 자른다" 는 회귀를 못 본다.
        """
        return [{
            "type": "if",
            "condition": f"flag_{i} == 1",
            "true_body": [{"type": "call", "name": f"on_{i}"}],
            "false_body": [{"type": "call", "name": f"off_{i}"}],
            "elif_chains": [],
        } for i in range(n)]

    def test_lowering_the_cap_still_bites(self):
        """올리는 쪽만 보면 '상한을 무시하게 만든' 회귀를 못 잡는다."""
        from generators import sts

        flow = self._sibling_ifs(4)
        info = {"name": "fn_many_ifs", "params": [], "return_type": "void"}
        # 먼저 **재료가 상한보다 많다**는 것을 확인한다 — 안 그러면 아래 단언이
        # "자르는 걸 봤다" 가 아니라 "재료가 원래 적었다" 를 통과시킨다.
        assert len(sts._generate_steps_from_flow(flow, info, max_tc=99)) > 3
        assert len(sts._generate_steps_from_flow(flow, info, max_tc=3)) == 3


class TestElifExpansionNeverInverts:
    """`elif_chains[:max_tc - 2]` 는 상한이 2 이하일 때 **음수 슬라이스**가 된다.

    `[:-1]` 은 "0개" 가 아니라 "마지막 하나만 버린다" 는 **반대 뜻**이다. 반환값
    (`test_cases[:max_tc]`)만 보면 어차피 잘려서 안 보이므로, out 파라미터를 그대로
    받는 `_walk_flow_nodes` 수준에서 잰다.
    """

    @staticmethod
    def _if_with_elifs(n: int):
        return [{
            "type": "if",
            "condition": "x > 0",
            "true_body": [],
            "false_body": [{"type": "return", "value": "0"}],
            "elif_chains": [{"condition": f"x == {i}", "body": []} for i in range(n)],
        }]

    def test_cap_of_one_expands_no_elif_branch(self):
        from generators import sts

        branch_tcs: list = []
        sts._walk_flow_nodes(self._if_with_elifs(3), [], branch_tcs, depth=0, max_tc=1)
        labels = [s["action"] for tc in branch_tcs for s in tc]
        assert not [a for a in labels if "else-if" in a], (
            f"상한 1 인데 else-if 분기가 확장됐다 — 음수 슬라이스다: {labels}")
        # 참/거짓 두 갈래는 남는다(그건 이 상한이 자르는 대상이 아니다).
        assert len(branch_tcs) == 2

    def test_a_generous_cap_expands_every_elif(self):
        from generators import sts

        branch_tcs: list = []
        sts._walk_flow_nodes(self._if_with_elifs(3), [], branch_tcs, depth=0, max_tc=9)
        n_elif = len([1 for tc in branch_tcs for s in tc if "else-if" in s["action"]])
        assert n_elif == 3, f"else-if {n_elif}개 — 상한을 올려도 확장이 안 늘어난다"


def test_nested_branch_bodies_get_the_same_cap():
    """분기 **안쪽**의 switch 도 같은 상한을 받는가.

    `_expand_branch_body` → `_walk_flow_nodes` 재귀에 상한을 안 넘기면, 바깥은 12 로
    확장되는데 한 겹 안쪽만 5 로 잘린다(같은 문서 안에서 깊이에 따라 상한이 달라진다).
    """
    from generators import sts

    inner_switch = {
        "type": "switch", "expr": "sub", "default_calls": [],
        "cases": [{"label": f"S{i}", "body": [f"inner_{i}"]} for i in range(8)],
    }
    branch_tcs: list = []
    sts._expand_branch_body([inner_switch], [], branch_tcs, depth=0, max_depth=4, max_tc=8)
    labels = [s["action"] for tc in branch_tcs for s in tc]
    got = len([a for a in labels if a.startswith("sub = S")])
    assert got == 8, f"안쪽 switch 분기가 {got}개 — 재귀가 상한을 안 받는다"


def test_the_gate_discloses_both_axes_of_the_tc_cap():
    """상한이 **두 축**에 걸린다는 사실이 공시 문구에 남아 있는가.

    이 시리즈가 고치는 대상은 결국 **게이트가 하는 말**이다. 코드가 두 축을 다 자르는데
    문구가 함수 루프만 말하면, 함수 1개짜리 요구에서 상한을 올린 사용자는 왜 산출이
    안 늘어나는지 알 길이 없다(고치기 전이 정확히 그 상태였다).
    """
    effect = str(req.DOC_REQUIREMENTS["sts"]["caps"]["max_tc_per_req"]["effect"])
    assert "함수 하나" in effect, (
        f"함수당 축이 공시에서 사라졌다: {effect!r}")


def test_expand_branch_body_has_no_unreachable_duplicate_arm():
    """같은 `if/elif` 사슬에 **글자까지 같은 조건**이 두 번 있으면 뒤쪽은 죽은 코드다.

    실제로 `if`/`switch`/`loop` 3분기가 그렇게 중복돼 있었다. 지웠고, 다시 들어오면
    (예: 병합 사고) 여기서 잡는다 — 죽은 분기는 `max_tc` 같은 인자를 넘겨도 아무 일도
    안 하면서 "처리한다" 는 인상만 준다.
    """
    import ast
    import inspect as _inspect

    from generators import sts

    tree = ast.parse(_inspect.getsource(sts._expand_branch_body))
    fn = tree.body[0]
    loop = next(n for n in ast.walk(fn) if isinstance(n, ast.For))
    conditions, node = [], next(s for s in loop.body if isinstance(s, ast.If))
    while isinstance(node, ast.If):
        conditions.append(ast.dump(node.test))
        node = node.orelse[0] if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If) else None
    dupes = [c for c in conditions if conditions.count(c) > 1]
    assert not dupes, f"도달 불가 중복 분기 {len(dupes)}개"
