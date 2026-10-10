"""UDS ASIL·Related 보강의 참조 문서는 **이 프로젝트의 SwUDS** 다 (R47 N25, 2026-09-10).

## 왜 생겼나

R46 라이브 UDS(kjpds02_pv, 정본 v3.03 을 `reference_doc_path` 로 지정) 의 게이트가 ASIL·Related
non-TBD **23.8% / 23.9%** 로 두 축 미달이었다. N23 으로 "문서 기재율인가 파서 매핑인가" 를 실측하니
둘 다 아니었다:

- `gen_stats.reference_suds`: `same_project:false (ref=HDPDM01 vs payload=KJPDS02)` ·
  `safety_fields_blocked:305 · applied:0` — 보강 참조가 `config.UDS_REF_SUDS_PATH` **기본값**(저장소
  `docs/` 의 HDPDM01 SUDS)이었다. 사용자가 준 정본은 **템플릿으로만** 쓰였다.
- 정본을 빌더와 같은 추출기(`_extract_function_info_from_docx`)로 열면 ASIL **988/988**·Related
  **988/988** 기재, payload 함수 951개 전부 정본에 있다. 배선만 이으면 23.8% → ≈99.8%.

## 이 파일이 고정하는 것

1. 참조 해석 헬퍼는 지정이 없을 때 **빈 값**을 낸다 — HDPDM01 기본값으로 대체하지 않는다.
2. 템플릿이 같은 파일의 로컬 사본이면 재사용한다(50MB 재로컬화 회피), 로컬 경로는 그대로.
3. 서브프로세스 환경에 `UDS_REF_SUDS_PATH` 가 실린다 — 빌더는 config 를 새로 import 하므로 이것이 배선이다.
4. jenkins 동기·비동기 호출부와 `_uds_generate_from_paths` 가 실제로 그 인자를 넘긴다.
5. `config` 가 env 를 읽는다(서브프로세스에서 확인) — 3 이 도달하는 마지막 홉.

뮤테이션(2026-09-10): `_docx_subprocess_env` 가 env 를 안 실으면 3·5 가, 호출부 kwarg 를 지우면 4 가 죽는다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("backend.helpers.uds")

from backend.helpers import uds as U  # noqa: E402


def _default_ref() -> str:
    import config
    return str(getattr(config, "UDS_REF_SUDS_PATH", "") or "")


class TestResolveReferenceSuds:

    def test_unspecified_is_empty_not_the_hdpdm01_default(self):
        got, why = U.resolve_reference_suds_for_generation("", None)
        assert got == ""
        assert why and "미지정" in why
        assert got != _default_ref() or _default_ref() == ""

    def test_template_that_is_the_same_source_path_is_reused(self, tmp_path):
        """로컬 사본 규약 `<tmp>/sha1(원경로)[:12]/<원본이름>` 과 맞을 때만 재사용한다."""
        import hashlib
        name = "(KJPDS02_SwUDS) Software Unit Design Specification_v3.03_260902.docx"
        raw = f"U:/docs/{name}"
        key = hashlib.sha1(raw.replace("\\", "/").lower().encode("utf-8")).hexdigest()[:12]
        tpl = tmp_path / key / name
        tpl.parent.mkdir()
        tpl.write_bytes(b"x")
        got, why = U.resolve_reference_suds_for_generation(raw, str(tpl))
        assert got == str(tpl)
        assert "재사용" in why and raw in why       # 어느 원본에서 왔는지 사후 판별 가능

    def test_same_name_from_another_tree_is_not_reused(self, tmp_path):
        """(리뷰 W3) cloudium 두 트리(`0002 A Cappella` / `1220 진행/0002 A Cappella`)의 동명 파일 —
        이름만 보면 다른 리비전의 ASIL 값이 실린다. 원본 경로 해시가 다르면 재사용하지 않는다."""
        import hashlib
        name = "(KJPDS02_SwUDS) Software Unit Design Specification_v3.03_260902.docx"
        other = f"U:/1200/0002 A Cappella/{name}"
        key_other = hashlib.sha1(other.replace("\\", "/").lower().encode("utf-8")).hexdigest()[:12]
        tpl = tmp_path / key_other / name
        tpl.parent.mkdir()
        tpl.write_bytes(b"x")
        got, _ = U.resolve_reference_suds_for_generation(f"U:/1200/1220 진행/0002 A Cappella/{name}", str(tpl))
        assert got != str(tpl)

    def test_existing_template_with_a_different_name_is_never_the_reference(self, tmp_path):
        """(리뷰 M1) 판정을 `True` 로 바꾸면 템플릿이 곧 참조가 된다 — 존재하는 템플릿 + 다른 이름."""
        tpl = tmp_path / "standard_template.docx"
        tpl.write_bytes(b"x")
        got, _ = U.resolve_reference_suds_for_generation(str(tmp_path / "nope" / "ref.docx"), str(tpl))
        assert got == ""

    def test_local_file_is_used_as_is(self, tmp_path):
        ref = tmp_path / "ref.docx"
        ref.write_bytes(b"x")
        got, why = U.resolve_reference_suds_for_generation(str(ref), None)
        assert got == str(ref)

    def test_unreadable_reference_stays_empty_with_reason(self, tmp_path):
        """읽지 못하면 비운 채 사유를 낸다 — 기본값으로 바꿔치기하지 않는다."""
        missing = str(tmp_path / "nope" / "missing.docx")
        got, why = U.resolve_reference_suds_for_generation(missing, None)
        assert got == ""
        assert why
        assert _default_ref() not in (got,)

    def test_reference_goes_through_the_same_resolver_as_the_template(self, monkeypatch):
        """(리뷰 W2) 템플릿과 같은 해석기(`resolve_builder_input`: 모드 분기·접근 검사·로컬화)를 탄다."""
        from backend.services import resolver_helpers as RH

        calls: list[str] = []

        def fake(path_str, *, label="", reasons=None):
            calls.append(path_str)
            if reasons is not None:
                reasons.append(f"{label}: 접근 거부 — 테스트")
            return None

        monkeypatch.setattr(RH, "resolve_builder_input", fake)
        got, why = U.resolve_reference_suds_for_generation("C:/Windows/win.ini", None)
        assert calls == ["C:/Windows/win.ini"]
        assert got == "" and "접근 거부" in why

    def test_template_name_match_requires_the_template_to_exist(self, tmp_path):
        ghost = str(tmp_path / "ref.docx")     # 템플릿 경로만 있고 파일은 없다
        got, _ = U.resolve_reference_suds_for_generation("U:/x/ref.docx", ghost)
        assert got != ghost


class TestSubprocessEnv:

    def test_env_carries_the_reference_path(self):
        env = U._docx_subprocess_env("D:/x/ref.docx")
        assert env["UDS_REF_SUDS_PATH"] == "D:/x/ref.docx"
        # 나머지 환경은 상속된다(PATH 등이 빠지면 서브프로세스가 못 뜬다).
        assert env.get("PATH") == os.environ.get("PATH")

    def test_empty_reference_is_passed_as_empty_even_when_ambient_env_has_one(self, monkeypatch):
        """(리뷰 W1) 키를 빼면 서브프로세스 config 가 HDPDM01 기본값이나 `.env` 의 값을 조용히 읽는다."""
        monkeypatch.setenv("UDS_REF_SUDS_PATH", "D:/ambient/other_project.docx")
        assert U._docx_subprocess_env("")["UDS_REF_SUDS_PATH"] == ""
        assert U._docx_subprocess_env(None)["UDS_REF_SUDS_PATH"] == ""

    def test_config_in_a_fresh_interpreter_sees_the_empty_reference(self):
        """빈 값이 넘어가면 서브프로세스 config 도 빈 값이다 — 기본값(HDPDM01)이 아니다."""
        env = dict(os.environ)
        env["UDS_REF_SUDS_PATH"] = ""
        code = "import config; print(repr(config.UDS_REF_SUDS_PATH))"
        run = subprocess.run([sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parents[2]),
                             env=env, capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stderr[-500:]
        assert run.stdout.strip() == "''"

    def test_builder_treats_empty_reference_as_absent(self):
        """`Path("")` 는 `.` 이라 `.exists()` 가 True 다 — 빌더는 빈 값·비파일을 참조 없음으로 읽어야 한다."""
        from report_gen import docx_builder
        from tests.unit._source_probe import source_of

        src = source_of(docx_builder.generate_uds_docx)
        assert 'str(UDS_REF_SUDS_PATH or "").strip() and ref_doc_path.is_file()' in src

    def test_generate_with_retry_passes_env_to_every_subprocess_call(self, tmp_path, monkeypatch):
        """관측량: 실제 `subprocess.run` 호출의 `env` 에 참조 경로가 있다 — 재시도 단계 전부."""
        seen: list[dict] = []

        def fake_run(cmd, **kw):
            seen.append(dict(kw.get("env") or {}))
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

        monkeypatch.setattr(U.subprocess, "run", fake_run)
        out = tmp_path / "out.docx"
        try:
            U._generate_docx_with_retry(None, {"function_details": {}}, out, retries=1,
                                        reference_suds_path="D:/proj/ref.docx")
        except Exception:   # silent-ok - 가짜 러너는 늘 실패한다; 관측량은 아래 env 다
            pass
        assert seen, "서브프로세스가 한 번도 호출되지 않았다"
        assert all(e.get("UDS_REF_SUDS_PATH") == "D:/proj/ref.docx" for e in seen), seen

    def test_config_reads_the_env_in_a_fresh_interpreter(self, tmp_path):
        """마지막 홉 — 서브프로세스의 `config.UDS_REF_SUDS_PATH` 가 env 값이다."""
        env = dict(os.environ)
        env["UDS_REF_SUDS_PATH"] = str(tmp_path / "ref.docx")
        code = "import config; print(config.UDS_REF_SUDS_PATH)"
        run = subprocess.run([sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parents[2]),
                             env=env, capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stderr[-500:]
        assert run.stdout.strip() == str(tmp_path / "ref.docx")


class TestCallSitesAreWired:

    def test_jenkins_sync_and_async_pass_the_reference(self):
        from backend.routers import jenkins
        from tests.unit._source_probe import source_of

        src = source_of(jenkins)
        # (R47-e N30) 서버가 최종 판정한다 — 폼이 먼저, 비면 레지스트리 정본. local 두 곳과 같은 함수.
        assert src.count("describe_reference_suds_source, reference_doc_path, source_root)") >= 2, \
            "jenkins 동기·비동기 UDS 핸들러 둘 다 참조 출처를 서버에서 판정해야 한다"
        assert src.count('resolve_reference_suds_for_generation, _ref_src["raw"]') >= 2, \
            "jenkins 동기·비동기 UDS 핸들러 둘 다 참조를 로컬화해야 한다"
        # 동기(lambda 인자)·비동기(kwarg) 두 곳 — 한 곳만 남으면 뮤턴트(M3)가 산다.
        assert src.count("reference_suds_path=_ref_suds") >= 2, "호출부 한 곳이 참조를 넘기지 않는다"
        # 신원 앵커·불일치 기록: 동기는 핸들러에서, 비동기는 payload 를 만드는 헬퍼로 출처를 넘긴다.
        assert "annotate_reference_source(uds_payload, source_root, _ref_src)" in src
        assert "reference_source=_ref_src" in src
        # 같은 정본이 템플릿 단일 규칙에도 들어간다(폼 → 레지스트리 순).
        assert src.count("reference_doc=reference_doc_path or _ref_src[\"raw\"]") >= 2
        # (R47-e 리뷰 W6) 레지스트리 락·정본 로컬화는 루프 밖 — local 과 같은 규약.
        assert src.count("await _run_blocking(describe_reference_suds_source, reference_doc_path, source_root)") >= 2
        assert src.count("await _run_blocking(resolve_reference_suds_for_generation, _ref_src[\"raw\"]") >= 2
        # (R47-e 리뷰 W5) AI 예시문 폴백이 HDPDM01 기본값(config·docs/*.txt)을 읽지 않는다 — 참조 SwUDS 를 쓴다.
        assert "Path(config.UDS_REF_SUDS_PATH)" not in src
        assert '"HDPDM01_UDS.txt"' not in src
        assert "ai_example_text = _read_text_from_file(Path(_ref_suds))" in src

    def test_generate_from_paths_forwards_to_the_retry_runner(self):
        from tests.unit._source_probe import source_of

        src = source_of(U._uds_generate_from_paths)
        assert "reference_suds_path=reference_suds_path" in src
        assert "reference_suds_path" in U._uds_generate_from_paths.__code__.co_varnames
        # (N30) 출처가 오면 payload 를 만든 직후 앵커·불일치를 새긴다.
        assert "annotate_reference_source(uds_payload, source_root, reference_source)" in src
        assert "reference_source" in U._uds_generate_from_paths.__code__.co_varnames

    def test_retry_runner_uses_the_env_helper(self):
        from tests.unit._source_probe import source_of

        assert "_docx_subprocess_env(reference_suds_path)" in source_of(U._generate_docx_with_retry)
