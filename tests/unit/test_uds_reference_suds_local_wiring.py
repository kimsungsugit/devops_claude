"""local UDS 경로도 **이 프로젝트의 SwUDS** 를 참조로 연다 — 폼이 없으면 레지스트리 `uds` 정본 (R47-d N29, 2026-09-10).

## 왜 생겼나

R47 N25 가 jenkins 동기·비동기 UDS 에 `reference_doc_path` → 참조 SwUDS 배선을 넣었을 때
`/api/local/uds/generate(-async)` 두 핸들러는 **폼 자체가 없어** 빈 값을 명시 주입했다 — 참조 없이 생성.
R47-c 보드 근거는 그것을 '미전달' 로 정직하게 보여 줬지만, 그 요청은 `source_root` 로 Quality DB 의
`scm_id` 를 채우고 있었다. **프로젝트를 알면서 그 프로젝트의 SwUDS 는 열지 않은** 것이다. 비동기 판의
로그는 심지어 "config 기본값을 읽는다" 고 거짓을 적었다(env 는 빈 값이었다).

리뷰(C1)가 두 번째 층을 찾았다: 배선을 이어도 빌더 신원 게이트는 payload 토큰(소스 루트 leaf
`NE1AW_PORTING`→{NE1AW, PORTING})과 정본 파일명 토큰({KJPDS02})을 비교하므로 등록된 두 프로젝트 **모두**
"다른 프로젝트" 로 판정돼 ASIL·Related 가 전부 차단된다 — 참조를 열고도 보강 0. 그래서 레지스트리 항목 id
(`kjpds02_pv`→{KJPDS02})를 신원 토큰에 얹는다(통과시키는 게 아니라 토큰을 하나 더 주는 것 — 잘못 등록된
uds 는 여전히 막힌다).

## 이 파일이 고정하는 것

1. 레지스트리 폴백은 `resolve_scm_entry`(정확일치·미상 None·**한 스냅샷**)로 항목을 고르고 `linked_docs.uds` 를 낸다.
   못 고르면 **빈 값 + 사유** — 후보가 하나뿐이어도 집지 않는다. `get_registry_entry` 재조회(두 스냅샷)는 하지 않는다.
2. 폼 `reference_doc_path` 가 있으면 레지스트리를 보지 않는다(사용자 지정 > 등록값).
3. 두 출처 모두 `resolve_reference_suds_for_generation` 으로 로컬화한다(jenkins 와 같은 접근 검사).
4. 신원 앵커: 항목이 풀리면 `summary.project` 에 id 를 얹고 `reference_suds_origin` 을 남긴다. 기존 값은 안 덮고, 못 풀면 안 얹는다.
5. local 동기·비동기 핸들러 둘 다 `reference_doc_path` 폼을 받고, 원 경로 선택→템플릿 단일 규칙(정본 우선, jenkins 와 같은
   `resolve_template_for`)→로컬화→앵커→`reference_suds_path=` 로 넘긴다.
   동기 판은 루프 밖(`_run_blocking`)에서 해석하고, AI 예시문도 그 참조를 쓴다(config 기본값 읽기 0곳).
6. 생성 뒤 결과 로그가 "열었다" 와 "적용됐다" 를 가른다(`log_reference_outcome`).
"""
from __future__ import annotations

import inspect
import json
import logging

import pytest

pytest.importorskip("backend.helpers.uds")

from backend.helpers import uds as U  # noqa: E402
from backend.schemas import ScmLinkedDocs, ScmRegistryEntry  # noqa: E402
from backend.services import scm_registry as R  # noqa: E402

_UDS_A = "U:/1200/1220 진행/0002 A Cappella/04 KJPDS02/01.SwUDS/(KJPDS02_SwUDS) Software Unit Design Specification_v3.03_260902.docx"
_UDS_B = "U:/1200/1220 진행/0002 A Cappella/03 NE_GN7/01.SUDS/(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx"


def _entry(eid: str, root: str, uds: str = "") -> ScmRegistryEntry:
    return ScmRegistryEntry(id=eid, name=eid.upper(), source_root=root, linked_docs=ScmLinkedDocs(uds=uds))


def _registry(monkeypatch, *entries: ScmRegistryEntry) -> None:
    monkeypatch.setattr(R, "list_registry_entries", lambda: list(entries))

    def _no_reread(eid):   # pragma: no cover - 호출되면 곧 실패
        raise AssertionError("두 번째 스냅샷(get_registry_entry) 을 읽으면 안 된다 — 리뷰 W2")
    monkeypatch.setattr(R, "get_registry_entry", _no_reread)


class TestRegistryFallback:

    def test_matching_source_root_yields_that_entrys_uds(self, monkeypatch):
        _registry(monkeypatch,
                  _entry("hdpdm01", "D:/Project/Ados/PDS64_RD,D:/Project/Ados/PDS64_FBL", _UDS_B),
                  _entry("kjpds02_pv", "C:/Project/Ados/NE1AW_PORTING,C:/Project/Ados/PDS128_FBL", _UDS_A))
        got, why, sid = U.resolve_reference_suds_from_registry("C:/Project/Ados/NE1AW_PORTING")
        assert (got, sid) == (_UDS_A, "kjpds02_pv")
        assert "kjpds02_pv" in why
        # 콤마 복수 경로도 같은 판정(`resolve_scm_id` 규칙 3) — 첫 조각이 아니라 전체가 한 항목이면 된다.
        got2, _, _ = U.resolve_reference_suds_from_registry("C:/Project/Ados/NE1AW_PORTING,C:/Project/Ados/PDS128_FBL")
        assert got2 == _UDS_A

    def test_entry_id_is_also_accepted(self, monkeypatch):
        _registry(monkeypatch, _entry("kjpds02_pv", "C:/src/a", _UDS_A))
        got, _, _ = U.resolve_reference_suds_from_registry("KJPDS02_PV")
        assert got == _UDS_A

    def test_empty_source_root_yields_nothing_with_a_reason(self, monkeypatch):
        _registry(monkeypatch, _entry("kjpds02_pv", "C:/src/a", _UDS_A))
        got, why, sid = U.resolve_reference_suds_from_registry("")
        assert (got, sid) == ("", "") and "source_root" in why

    def test_unmatched_root_does_not_pick_the_sole_entry(self, monkeypatch):
        """후보가 하나뿐이어도 집지 않는다 — `items[0]` 폴백이 남의 프로젝트 ASIL 을 실었던 그 패턴."""
        _registry(monkeypatch, _entry("kjpds02_pv", "C:/src/a", _UDS_A))
        got, why, sid = U.resolve_reference_suds_from_registry("C:/src/other")
        assert (got, sid) == ("", "")
        assert "정확히 맞지 않아" in why and "C:/src/other" in why

    def test_two_entries_sharing_a_root_is_unknown(self, monkeypatch):
        _registry(monkeypatch, _entry("a", "C:/src/shared", _UDS_A), _entry("b", "C:/src/shared", _UDS_B))
        got, _, sid = U.resolve_reference_suds_from_registry("C:/src/shared")
        assert (got, sid) == ("", "")

    def test_entry_without_uds_yields_nothing_but_still_names_the_entry(self, monkeypatch):
        """uds 가 비어도 항목 id 는 돌려준다 — 신원 앵커는 참조 문서가 없어도 정당하다."""
        _registry(monkeypatch, _entry("kjpds02_pv", "C:/src/a", ""))
        got, why, sid = U.resolve_reference_suds_from_registry("C:/src/a")
        assert got == "" and sid == "kjpds02_pv" and "등록돼 있지 않다" in why

    def test_registry_failure_is_a_reason_not_an_exception(self, monkeypatch):
        def _boom():
            raise RuntimeError("registry unreadable")
        monkeypatch.setattr(R, "list_registry_entries", _boom)
        got, why, sid = U.resolve_reference_suds_from_registry("C:/src/a")
        assert (got, sid) == ("", "") and "RuntimeError" in why

    def test_single_snapshot_resolver_is_the_same_judgment_as_resolve_scm_id(self, monkeypatch):
        """(리뷰 W2) `resolve_scm_entry` 와 `resolve_scm_id` 는 한 판정의 두 투영이다 — 갈리면 recorder 와 참조가 다른 프로젝트를 본다."""
        _registry(monkeypatch,
                  _entry("hdpdm01", "D:/Project/Ados/PDS64_RD,D:/Project/Ados/PDS64_FBL", _UDS_B),
                  _entry("kjpds02_pv", "C:/Project/Ados/NE1AW_PORTING", _UDS_A))
        for probe in ("C:/Project/Ados/NE1AW_PORTING", "hdpdm01", "D:/nope", "", "D:/Project/Ados/PDS64_FBL"):
            entry = R.resolve_scm_entry(probe)
            assert R.resolve_scm_id(probe) == (entry.id if entry is not None else None), probe


class TestSourcePick:
    """`pick_reference_suds_source` — 원 경로 선택. 로컬화는 호출자가 `resolve_reference_suds_for_generation` 으로."""

    def test_form_path_wins_over_registry(self, monkeypatch, tmp_path):
        seen = {}

        def _fake_from_registry(root):
            seen["called"] = True
            return _UDS_A, "레지스트리", "kjpds02_pv"
        monkeypatch.setattr(U, "resolve_reference_suds_from_registry", _fake_from_registry)
        raw, why, origin = U.pick_reference_suds_source("D:/form/ref.docx", str(tmp_path))
        assert (raw, why, origin) == ("D:/form/ref.docx", "폼 reference_doc_path", "form")
        assert "called" not in seen, "폼이 있으면 레지스트리를 보지 않는다"

    def test_empty_form_falls_back_to_registry(self, monkeypatch, tmp_path):
        _registry(monkeypatch, _entry("kjpds02_pv", str(tmp_path), _UDS_A))
        raw, why, origin = U.pick_reference_suds_source("", str(tmp_path))
        assert (raw, origin) == (_UDS_A, "registry:kjpds02_pv") and "레지스트리 kjpds02_pv 의 uds 정본" in why

    def test_registry_path_localizes_through_the_same_resolver_as_the_form(self, monkeypatch, tmp_path):
        """관측량: 레지스트리 원 경로도 `resolve_reference_suds_for_generation` 에서 로컬 파일이 된다(접근 검사 비대칭 금지)."""
        reg_ref = tmp_path / "(KJPDS02_SwUDS) x.docx"
        reg_ref.write_bytes(b"PK")
        _registry(monkeypatch, _entry("kjpds02_pv", str(tmp_path), str(reg_ref)))
        raw, _, _ = U.pick_reference_suds_source("", str(tmp_path))
        got, _why = U.resolve_reference_suds_for_generation(raw, None)
        assert got and got.endswith("(KJPDS02_SwUDS) x.docx")

    def test_nothing_anywhere_is_empty_with_the_registry_reason(self, monkeypatch):
        _registry(monkeypatch, _entry("kjpds02_pv", "C:/src/a", ""))
        raw, why, origin = U.pick_reference_suds_source("", "C:/src/a")
        assert (raw, origin) == ("", "") and "등록돼 있지 않다" in why

    def test_missing_registry_yields_nothing_not_a_default(self, monkeypatch, tmp_path):
        """`config.UDS_REF_SUDS_PATH` 기본값(HDPDM01)으로 대체하지 않는다."""
        _registry(monkeypatch)
        import config
        monkeypatch.setattr(config, "UDS_REF_SUDS_PATH", str(tmp_path / "default.docx"), raising=False)
        raw, _, origin = U.pick_reference_suds_source("", "C:/src/a")
        assert (raw, origin) == ("", "")


class TestIdentityAnchor:
    """(리뷰 C1) 참조를 열고도 신원 게이트가 막던 두 번째 층."""

    def test_registry_id_becomes_a_project_token_that_matches_the_reference(self, monkeypatch):
        from report_gen.docx_builder import _project_tokens
        _registry(monkeypatch, _entry("kjpds02_pv", "C:/Project/Ados/NE1AW_PORTING", _UDS_A))
        payload = {"project_name": "NE1AW_PORTING", "module_name": "NE1AW_PORTING", "summary": {}}
        # 실측 전제: leaf 토큰만으론 정본과 교집합이 없다.
        from pathlib import Path
        assert not (_project_tokens("NE1AW_PORTING") & _project_tokens(Path(_UDS_A).stem))
        sid = U.anchor_project_identity(payload, "C:/Project/Ados/NE1AW_PORTING", "registry:kjpds02_pv")
        assert sid == "kjpds02_pv"
        assert payload["summary"]["project"] == "kjpds02_pv"
        assert payload["reference_suds_origin"] == "registry:kjpds02_pv"
        assert _project_tokens(payload["summary"]["project"]) & _project_tokens(Path(_UDS_A).stem) == {"KJPDS02"}

    def test_anchor_does_not_make_a_misregistered_reference_pass(self, monkeypatch):
        """R46 이전 실상: hdpdm01 항목의 uds 가 KJPDS02 문서를 가리켰다 — 앵커를 얹어도 {HDPDM01}∩{KJPDS02}=∅."""
        from pathlib import Path

        from report_gen.docx_builder import _reference_identity_verdict
        _registry(monkeypatch, _entry("hdpdm01", "D:/Project/Ados/PDS64_RD", _UDS_A))
        payload = {"project_name": "PDS64_RD", "module_name": "PDS64_RD", "summary": {}}
        U.anchor_project_identity(payload, "D:/Project/Ados/PDS64_RD", "registry:hdpdm01")
        verdict = _reference_identity_verdict(payload, Path(_UDS_A))
        assert verdict["same_project"] is False and verdict["reason"] == "token_mismatch"

    def test_builder_verdict_flips_to_same_project_with_the_anchor(self, monkeypatch):
        """관측량: 빌더 판정 함수 자체로 확인 — 앵커 전 False, 후 True."""
        from pathlib import Path

        from report_gen.docx_builder import _reference_identity_verdict
        _registry(monkeypatch, _entry("kjpds02_pv", "C:/Project/Ados/NE1AW_PORTING", _UDS_A))
        payload = {"project_name": "NE1AW_PORTING", "module_name": "NE1AW_PORTING", "summary": {}}
        assert _reference_identity_verdict(payload, Path(_UDS_A))["same_project"] is False
        U.anchor_project_identity(payload, "C:/Project/Ados/NE1AW_PORTING", "registry:kjpds02_pv")
        v = _reference_identity_verdict(payload, Path(_UDS_A))
        assert v["same_project"] is True and v["shared_tokens"] == ["KJPDS02"]

    def test_existing_summary_project_is_not_overwritten(self, monkeypatch):
        _registry(monkeypatch, _entry("kjpds02_pv", "C:/src/a", _UDS_A))
        payload = {"summary": {"project": "ALREADY"}}
        assert U.anchor_project_identity(payload, "C:/src/a", "form") == "kjpds02_pv"
        assert payload["summary"]["project"] == "ALREADY"

    def test_unresolved_root_adds_no_token_and_no_guess(self, monkeypatch):
        _registry(monkeypatch, _entry("kjpds02_pv", "C:/src/a", _UDS_A))
        payload = {"summary": {}}
        assert U.anchor_project_identity(payload, "C:/src/other", "") == ""
        assert payload == {"summary": {}}, "항목을 못 고르면 아무것도 바꾸지 않는다"

    def test_origin_is_recorded_even_when_the_registry_lookup_fails(self, monkeypatch):
        def _boom():
            raise RuntimeError("x")
        monkeypatch.setattr(R, "list_registry_entries", _boom)
        payload = {"summary": {}}
        assert U.anchor_project_identity(payload, "C:/src/a", "form") == ""
        assert payload["reference_suds_origin"] == "form" and "project" not in payload["summary"]


class TestOutcomeLog:
    """(리뷰 X8) "열었다" 와 "적용됐다" 를 가르는 결과 로그 — 해석 성공 로그만 있으면 차단도 성공으로 읽힌다."""

    def _stats(self, tmp_path, ref):
        from report_gen.docx_builder import gen_stats_path
        out = tmp_path / "out.docx"
        gen_stats_path(str(out)).write_text(json.dumps({"reference_suds": ref}), encoding="utf-8")
        return out

    def test_blocked_reference_logs_a_warning_naming_the_tokens(self, tmp_path, caplog):
        out = self._stats(tmp_path, {
            "configured": True, "document": "(KJPDS02_SwUDS) x.docx", "origin": "registry:kjpds02_pv",
            "identity": {"same_project": False, "reason": "token_mismatch", "ref_tokens": ["KJPDS02"],
                         "payload_tokens": ["NE1AW", "PORTING"]},
            "safety_fields_applied": 0, "safety_fields_blocked": 305,
        })
        with caplog.at_level(logging.INFO, logger="devops_api"):
            res = U.log_reference_outcome(out)
        rec = [r for r in caplog.records if "UDS 참조 SwUDS 결과" in r.getMessage()]
        assert rec and rec[-1].levelno == logging.WARNING
        msg = rec[-1].getMessage()
        assert "불일치" in msg and "차단 305" in msg and "KJPDS02" in msg and "NE1AW" in msg
        assert res["same_project"] is False and res["blocked"] == 305

    def test_applied_reference_logs_info(self, tmp_path, caplog):
        out = self._stats(tmp_path, {
            "configured": True, "document": "(KJPDS02_SwUDS) x.docx", "origin": "form",
            "identity": {"same_project": True, "reason": "token_match", "shared_tokens": ["KJPDS02"]},
            "safety_fields_applied": 710, "safety_fields_blocked": 0,
        })
        with caplog.at_level(logging.INFO, logger="devops_api"):
            U.log_reference_outcome(out)
        rec = [r for r in caplog.records if "UDS 참조 SwUDS 결과" in r.getMessage()]
        assert rec and rec[-1].levelno == logging.INFO and "적용 710" in rec[-1].getMessage()

    def test_unconfigured_and_missing_stats_are_warnings_not_silence(self, tmp_path, caplog):
        out = self._stats(tmp_path, {"configured": False, "identity": {"same_project": None}})
        with caplog.at_level(logging.INFO, logger="devops_api"):
            assert U.log_reference_outcome(out)["present"] is True
            assert U.log_reference_outcome(tmp_path / "absent.docx") == {"present": False}
        msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("참조 없이 생성" in m for m in msgs) and any("미상" in m for m in msgs)

    def test_retry_runner_calls_the_outcome_log_on_success(self):
        """네 호출부 공통 지점(`_generate_docx_with_retry` 성공 분기)에서 부른다 — 한 곳이면 빠질 수 없다."""
        from tests.unit._source_probe import source_of
        src = source_of(U._generate_docx_with_retry)
        assert "log_reference_outcome(out_path)" in src


class TestLocalCallSitesAreWired:

    def test_both_local_handlers_accept_the_form_field(self):
        from backend.routers import local
        for fn in (local.local_uds_generate, local.local_uds_generate_async):
            params = inspect.signature(fn).parameters
            assert "reference_doc_path" in params, fn.__name__
            assert params["reference_doc_path"].default is not inspect.Parameter.empty

    def test_both_local_handlers_resolve_anchor_and_forward_the_reference(self):
        from backend.routers import local
        from tests.unit._source_probe import source_of

        for name in ("local_uds_generate", "local_uds_generate_async"):
            src = source_of(getattr(local, name))
            assert "pick_reference_suds_source(reference_doc_path, source_root)" in src, name
            assert "resolve_reference_suds_for_generation" in src, f"{name} 이 원 경로를 로컬화하지 않는다"
            # 같은 정본이 템플릿(heading 집합)이기도 하다 — jenkins 와 같은 단일 규칙(저장소 가드 `test_docgen_template_source` 가 이름으로 짝짓는다).
            assert "reference_doc=reference_doc_path or _ref_raw" in src, f"{name} 이 정본을 템플릿 단일 규칙에 넘기지 않는다"
            assert "anchor_project_identity(uds_payload, source_root, _ref_origin)" in src, name
            assert "reference_suds_path=_ref_suds" in src, f"{name} 이 해석 결과를 생성기에 넘기지 않는다"
            # 옛 거짓 로그("config 기본값을 읽는다")·N29 대기 문구가 남아 있으면 안 된다.
            assert "config.UDS_REF_SUDS_PATH 기본값을 읽는다" not in src, name
            assert "배선은 N29" not in src, name

    def test_sync_handler_resolves_off_the_event_loop(self):
        """(리뷰 W1) cloudium 이면 해석이 정본 수십 MB 를 워커로 받는다 — 루프에서 직접 돌리면 다른 요청이 선다."""
        from backend.routers import local
        from tests.unit._source_probe import source_of
        src = source_of(local.local_uds_generate)
        assert "await _run_blocking(resolve_reference_suds_for_generation, _ref_raw, tpl_path)" in src, (
            "동기 핸들러의 참조 로컬화가 `_run_blocking` 안에 있지 않다")
        i = src.find('resolve_template_for, "uds"')
        assert i > 0 and "await _run_blocking(" in src[max(0, i - 80): i], "템플릿 해석(정본 로컬화)도 루프 밖이어야 한다"

    def test_sync_handler_ai_example_reads_the_same_reference_not_the_config_default(self):
        """(리뷰 W3) 예시문 경로는 신원 게이트를 안 본다 — 기본값(HDPDM01) 본문이 프롬프트에 실리던 두 번째 사이트."""
        from backend.routers import local
        from tests.unit._source_probe import source_of
        src = source_of(local.local_uds_generate)
        assert "Path(config.UDS_REF_SUDS_PATH)" not in src, "기본값 읽기 코드가 남아 있다(주석은 제외)"
        assert "example_text = _read_text_from_file(Path(_ref_suds))" in src
        # 참조 해석이 AI 블록보다 앞에 있어야 예시문이 그 값을 볼 수 있다.
        assert src.find("pick_reference_suds_source") < src.find("if ai_enable:")
