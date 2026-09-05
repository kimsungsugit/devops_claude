"""UDS 품질 기록의 **정직성** 가드 (2026-08-24).

## 왜 이 파일이 있나

`generation_runs` 의 uds 행은 `elapsed_sec` · `ai_model` · `meta_json` 이 **전부 NULL**
이었다. sts/suts/sits 는 셋 다 싣는데(`generators/sts.py` 의 `record_run` 호출) UDS 만
비어서, "어느 모델로 얼마나 걸려 만들었나" 를 UDS 에 대해서만 물을 수 없었다.

원인은 호출부가 **다섯**이라는 것이다 — 진입점이 4개(jenkins 동기/비동기 · local
동기/비동기)이고 local 동기는 doc_only/full 두 갈래다. 인자를 각자 채우면 경로마다
다른 열이 비어 "어느 경로로 만들었나" 가 섞인다. 그래서 인자는 `_uds_record_kwargs`,
기록 자체는 `_record_uds_run` **관문** 하나로 묶었고, **이 파일은 다섯 곳이 실제로
그 관문을 지나는지** 를 고정한다.

두 번째 축은 지표의 오독이다. `input_pct 98.3%` 는 거짓이 아니지만 "입력이 잘
채워졌다" 로 읽힌다 — 실측하면 그 중 **79.4%가 `[IN] (none)`**(파라미터 없음) 이었다.
`(none)` 은 `void f(void)` 에 대한 **정확한** 기술이므로 미채움으로 세면 정상 함수를
벌하게 된다(payload 350함수 중 278이 `(none)` 인데 prototype 대조 결과 **전부 진짜
void**, 추출 실패는 0건). 그래서 게이트 축은 그대로 두고 실질 채움을 **참고지표**로
나란히 놓았다. 이 파일은 두 축이 서로를 침범하지 않는지 고정한다.

세 번째 축은 **게이트가 문서를 안 본다**는 것이다(2026-08-25 추가). 게이트는
`_compute_quick_quality_gate(uds_payload)` 라 이름 그대로 payload 만 본다. 라이터는
템플릿 주도라 대응 heading 이 없는 함수는 문서에서 조용히 빠지는데, payload 가
완벽하면 문서가 비어 있어도 만점이 나온다. 실측(`reports/quality.sqlite` ⋈ sidecar):

    run 660·661 = payload 5개 중 문서 반영 **0개**(빈 heading 419) → gate PASS · 점수 **100.0**
    run 674     = 350개 중 252개(72.0%), 미반영 98             → gate PASS · 점수 99.5

판정은 바꾸지 않는다 — 템플릿이 **의도된 부분집합**일 수 있어 뒤집으면 대량 오탐이다.
대신 `artifact_match_pct` 를 같은 자리에 참고지표로 올려 만점 옆에 반영률 0.0 이
보이게 했다. 이 파일은 그 축이 **미측정과 0% 를 섞지 않는지** 를 고정한다.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from backend.helpers import _uds_record_kwargs
from backend.helpers.common import _has_meaningful_value, _has_real_interface_value
from backend.helpers.uds import _uds_artifact_fidelity, _with_artifact_fidelity
from workflow.quality.evaluator import compute_gate_verdict, evaluate_uds

REPO = pathlib.Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# 1. 기록 메타 — 모르는 것을 지어내지 않는다
# --------------------------------------------------------------------------
class TestRecordKwargsDoesNotFabricate:
    def test_ai_model_omitted_when_ai_was_not_used(self):
        """AI 를 안 쓴 경로에 모델명을 실으면 DB 에 거짓이 남는다.

        jenkins 동기 경로(`/api/jenkins/uds/generate`)에는 AI 섹션 생성 단계가 **없다**.
        설정 파일에 모델명이 적혀 있다는 이유로 그것을 기록하면 "그 모델이 이 문서를
        만들었다" 는 주장이 된다.
        """
        kw = _uds_record_kwargs(source_root="D:/src", out_path="D:/o.docx", ai_used=False)
        assert "ai_model" not in kw
        assert kw["meta"]["ai_used"] is False
        assert "ai_model" not in kw["meta"]

    def test_elapsed_absent_is_not_zero(self):
        """측정하지 않은 소요시간은 부재여야 한다 — 0.0 은 '즉시 끝났다' 는 주장이다."""
        kw = _uds_record_kwargs(source_root="", out_path="x")
        assert "elapsed_sec" not in kw

    def test_elapsed_recorded_when_t0_given(self):
        from time import time
        kw = _uds_record_kwargs(source_root="", out_path="x", t0=time() - 2.0)
        assert kw["elapsed_sec"] >= 1.5      # 스케줄링 여유
        assert kw["elapsed_sec"] < 60.0

    def test_extra_meta_none_values_are_dropped(self):
        """모르는 값은 키 자체를 남기지 않는다(NULL 을 '없음' 으로 위장하지 않기)."""
        kw = _uds_record_kwargs(source_root="", out_path="x",
                                extra_meta={"entry": "e", "build_selector": None})
        assert kw["meta"]["entry"] == "e"
        assert "build_selector" not in kw["meta"]

    def test_ai_model_recorded_when_used(self, monkeypatch):
        import backend.helpers.uds as uds_mod
        monkeypatch.setattr(uds_mod, "_resolve_uds_ai_model", lambda: "test-model-x")
        kw = _uds_record_kwargs(source_root="", out_path="x", ai_used=True)
        assert kw["ai_model"] == "test-model-x"
        assert kw["meta"]["ai_model"] == "test-model-x"

    def test_ai_used_true_but_model_unknown_records_no_model(self, monkeypatch):
        """AI 는 썼는데 모델을 모르면 `ai_used` 만 남기고 모델명은 비운다."""
        import backend.helpers.uds as uds_mod
        monkeypatch.setattr(uds_mod, "_resolve_uds_ai_model", lambda: "")
        kw = _uds_record_kwargs(source_root="", out_path="x", ai_used=True)
        assert "ai_model" not in kw
        assert kw["meta"]["ai_used"] is True


# --------------------------------------------------------------------------
# 2. 다섯 호출부가 한 세트인지 — 하나만 빠지면 그 경로만 NULL 이 된다
# --------------------------------------------------------------------------
_RECORD_SITES = {
    "backend/helpers/uds.py": 1,        # jenkins generate-async
    "backend/routers/jenkins.py": 1,    # jenkins generate (동기)
    "backend/routers/local.py": 3,      # local generate (doc_only / full) + generate-async
}


def _calls_named(rel, name):
    """`rel` 안의 `name(...)` 호출 노드들. 이름은 **정확히** 일치해야 한다 —
    `endswith` 로 보면 `_record_uds_run` 이 `record_uds_run` 에도 걸려 두 계층이 섞인다."""
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    return [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
    ]


@pytest.mark.parametrize("rel,expected", sorted(_RECORD_SITES.items()))
def test_every_generate_path_records_through_the_gateway(rel, expected):
    """다섯 생성 경로는 전부 `_record_uds_run(...)` 관문을 지나야 한다.

    AST 로 본다 — 문자열 검색은 주석/독스트링에 속는다. 새 진입점을 추가하면서
    `record_uds_run` 을 직접 부르면 그 경로만 인자·산출물 충실도가 빠진다.
    """
    calls = _calls_named(rel, "_record_uds_run")
    assert len(calls) == expected, f"{rel}: _record_uds_run 호출 {len(calls)}개 (기대 {expected})"
    for call in calls:
        assert not call.keywords or all(kw.arg for kw in call.keywords), (
            f"{rel}:{call.lineno} — 관문에는 `**kwargs` 펼침이 아니라 이름 인자를 준다."
        )


@pytest.mark.parametrize("rel", sorted(_RECORD_SITES))
def test_recorder_is_reached_only_through_the_gateway(rel):
    """`record_uds_run`(recorder) 직접 호출은 관문 **안** 한 곳뿐이어야 한다.

    호출부가 recorder 를 직접 부르면 `elapsed_sec`/`ai_model`/`meta`/충실도를 다섯 곳에
    복제해야 하고, 그러면 한쪽만 고쳐진다 — 이 저장소가 반복해 겪은 패턴이다.
    """
    calls = _calls_named(rel, "record_uds_run")
    if rel != "backend/helpers/uds.py":
        assert not calls, (
            f"{rel}:{calls[0].lineno if calls else '-'} 가 recorder 를 직접 부른다. "
            "`_record_uds_run(...)` 관문을 쓸 것."
        )
        return
    assert len(calls) == 1, f"관문 밖에서도 recorder 를 부른다 ({len(calls)}회)"
    [call] = calls
    src = (REPO / rel).read_text(encoding="utf-8")
    gateway = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "_record_uds_run"
    )
    assert gateway.lineno <= call.lineno <= (gateway.end_lineno or 0), (
        "recorder 호출이 관문 밖에 있다"
    )
    spread = [
        kw for kw in call.keywords
        if kw.arg is None                      # ** 펼침
        and isinstance(kw.value, ast.Call)
        and isinstance(kw.value.func, ast.Name)
        and kw.value.func.id == "_uds_record_kwargs"
    ]
    assert spread, (
        "관문이 `**_uds_record_kwargs(...)` 를 안 쓴다 — 인자를 손으로 채우면 "
        "elapsed_sec/ai_model/meta 가 NULL 이 된다."
    )


def test_record_sites_are_not_silently_dropped():
    """호출부 총수를 고정한다 — 진입점이 늘거나 줄면 여기서 먼저 보이게."""
    total = sum(_RECORD_SITES.values())
    assert total == 5, "UDS 기록 호출부는 5곳이다(진입점 4 + local 동기의 doc_only 분기)"


# --------------------------------------------------------------------------
# 3. 채움 축 vs 실질 축 — 서로 다른 질문이고 섞이면 안 된다
# --------------------------------------------------------------------------
class TestTwoFillAxesStaySeparate:
    @pytest.mark.parametrize("value", [["[IN] (none)"], ["[OUT] (none)"], ["Name=[INOUT] (none)"], "(none)"])
    def test_none_is_written_but_not_real(self, value):
        """`(none)` 은 '적었다' 로는 참, '실제 항목이 있다' 로는 거짓."""
        assert _has_meaningful_value(value) is True
        assert _has_real_interface_value(value) is False

    @pytest.mark.parametrize("value", [["[IN] U16 u16t_Data"], ["Name=[INOUT] u8g_SysUds_WdbiCmd"],
                                       ["[IN] (none)", "[IN] U8 x"]])
    def test_real_values_pass_both(self, value):
        assert _has_meaningful_value(value) is True
        assert _has_real_interface_value(value) is True

    def test_empty_fails_both(self):
        assert _has_meaningful_value([]) is False
        assert _has_real_interface_value([]) is False

    def test_direction_tag_alone_is_not_a_value(self):
        """방향 태그만 있고 알맹이가 없으면 실질 항목이 아니다."""
        assert _has_real_interface_value(["[IN]"]) is False
        assert _has_real_interface_value(["[OUT] "]) is False


# --------------------------------------------------------------------------
# 4. evaluate_uds 의 게이트 축 / 참고 축 경계
# --------------------------------------------------------------------------
def _eval(rates: dict) -> dict:
    metrics = evaluate_uds({"quick_gate": {"rates": rates, "counts": {"total_functions": 10}},
                            "gate_pass": True, "confidence_gate_pass": True})
    return {m["metric_name"]: m for m in metrics}


_FULL_RATES = {
    "called_fill": 100.0, "calling_fill": 100.0, "input_fill": 98.3, "output_fill": 100.0,
    "description_fill": 100.0, "asil_fill": 98.0, "related_fill": 100.0,
    "global_fill": 75.4, "static_fill": 39.4,
    "input_real_fill": 18.9, "output_real_fill": 28.9,
    "description_trusted_fill": 85.1, "asil_trusted_fill": 86.6, "related_trusted_fill": 100.0,
}


class TestEvaluateUdsAxes:
    def test_real_fill_is_recorded_and_not_gated(self):
        """실질 채움은 기록되되 판정하지 않는다.

        `(none)` 은 void 함수의 정확한 기술이라 낮다고 결함이 아니다. threshold 를 붙이면
        정상 모듈이 떨어진다.
        """
        by = _eval(_FULL_RATES)
        for name, want in (("input_real_pct", 18.9), ("output_real_pct", 28.9)):
            assert name in by, f"{name} 이 기록되지 않는다"
            assert by[name]["value"] == want
            assert by[name]["threshold"] is None, f"{name} 에 threshold 가 붙으면 이중 판정이 된다"

    def test_trusted_axes_are_recorded_individually(self):
        """근거 축은 `confidence_gate_pass` boolean 하나로 뭉개지면 안 된다."""
        by = _eval(_FULL_RATES)
        assert by["description_trusted_pct"]["value"] == 85.1
        assert by["asil_trusted_pct"]["value"] == 86.6
        assert by["related_trusted_pct"]["value"] == 100.0
        for n in ("description_trusted_pct", "asil_trusted_pct", "related_trusted_pct"):
            assert by[n]["threshold"] is None, "판정 주체는 confidence_gate_pass 하나여야 한다"

    def test_global_static_stay_non_gated(self):
        """`config` 에 `global_min`/`static_min` 이 있어도 **일부러** 게이트가 아니다.

        전역/정적 변수가 적은 정상 모듈이 구조적으로 저평가되는 것을 막는 결정이다.
        미배선 결함으로 오인해 붙이지 말 것 — 이 테스트가 그 되돌림을 막는다.
        """
        by = _eval(_FULL_RATES)
        assert by["global_pct"]["threshold"] is None
        assert by["static_pct"]["threshold"] is None

    def test_gated_axes_are_exactly_seven(self):
        """게이트 축이 늘거나 줄면 판정 기준이 조용히 바뀐 것이다."""
        metrics = evaluate_uds({"quick_gate": {"rates": _FULL_RATES}, "gate_pass": True})
        gated = [m["metric_name"] for m in metrics if m["threshold"] is not None]
        assert sorted(gated) == sorted([
            "called_pct", "calling_pct", "input_pct", "output_pct",
            "description_pct", "asil_pct", "related_pct",
        ])
        assert compute_gate_verdict(metrics)["gated_count"] == 7

    def test_new_axes_do_not_change_the_verdict(self):
        """참고지표를 추가해도 판정은 그대로여야 한다(음성 대조군).

        `input_real_pct` 가 18.9 로 낮은데 verdict 가 흔들린다면 참고 축이 판정에
        새어 들어간 것이다.
        """
        metrics = evaluate_uds({"quick_gate": {"rates": _FULL_RATES}, "gate_pass": True})
        verdict = compute_gate_verdict(metrics)
        assert verdict["gate_pass"] is True
        assert verdict["failed_count"] == 0

    def test_missing_real_fill_rate_does_not_crash(self):
        """옛 사이드카(실질 축 없음)를 읽어도 죽지 않고 0.0 으로 기록된다."""
        rates = {k: v for k, v in _FULL_RATES.items() if not k.endswith("_real_fill")}
        by = _eval(rates)
        assert by["input_real_pct"]["value"] == 0.0


# --------------------------------------------------------------------------
# 5. 절단 상한 — 조용히 자르지 않는다
# --------------------------------------------------------------------------
def _load_repo_config():
    r"""**이 저장소의** `config.py` 를 경로로 직접 읽어 새 모듈로 돌려준다.

    ⚠ `import config` 에 기대면 안 된다. `tools/verify_uds_runtime.py:9` 와
    `tools/tmp_regen_once.py:10` 이 **다른 저장소**(`D:/Project/devops/260105`)를
    `sys.path[0]` 에 삽입하는데, 그 저장소에도 `config.py` 가 있다. 병렬(`-n auto`)
    실행에서 같은 워커에 그 모듈이 먼저 로드되면 `import config` 가 **남의 저장소
    파일**로 해석된다 — 실측(pre-commit 게이트): 단독 55건 통과인데 전량 병렬에서
    이 클래스만 실패했고, 값이 남의 `config` 에서 왔다:

        assert 1200 == 77
         +  where 1200 = <module 'config' from 'D:\Project\devops\260105\config.py'>...

    순서 의존이라 재현이 어렵다. `sys.modules['config']` 도 건드리지 않는다 —
    `importlib.reload` 로 갈아끼우면 같은 워커의 다른 테스트가 그 값을 본다.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_repo_config_under_test", REPO / "config.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTruncationCapsAreHonest:
    def test_source_file_cap_is_env_overridable(self):
        """`DEVOPS_UDS_MAX_FILES` 가 실제로 먹어야 한다.

        `config.py` 아래쪽에 `UDS_MAX_SOURCE_FILES = 1200` 이 **다시 할당**돼 있어서
        환경변수가 영구 무효였다(파이썬은 나중 할당이 이긴다). 경고도 없어 아무도 몰랐다.
        같은 형태의 재할당이 다시 들어오면 여기서 잡힌다.
        """
        import os

        old = os.environ.get("DEVOPS_UDS_MAX_FILES")
        try:
            os.environ["DEVOPS_UDS_MAX_FILES"] = "77"
            cfg = _load_repo_config()
            assert cfg.UDS_MAX_SOURCE_FILES == 77, (
                "환경변수가 무시된다 — config 아래쪽에서 같은 이름을 재할당하고 있지 않은지 볼 것"
            )
        finally:
            if old is None:
                os.environ.pop("DEVOPS_UDS_MAX_FILES", None)
            else:
                os.environ["DEVOPS_UDS_MAX_FILES"] = old

    def test_cap_falls_back_when_env_absent(self):
        """음성 대조군 — env 가 없으면 기본값이어야 한다.
        이걸 안 보면 "항상 77" 같은 구현도 위 테스트를 통과한다."""
        import os

        old = os.environ.pop("DEVOPS_UDS_MAX_FILES", None)
        try:
            assert _load_repo_config().UDS_MAX_SOURCE_FILES == 1200
        finally:
            if old is not None:
                os.environ["DEVOPS_UDS_MAX_FILES"] = old

    def test_dead_lookalike_constant_stays_removed(self):
        """`UDS_MAX_ITEMS_PER_CATEGORY` 는 소비처가 0곳인 죽은 상수였다.

        실제 절단은 `UDS_MAX_FUNCTION_ITEMS` 가 한다. 이름이 비슷해 어느 쪽이 진짜인지
        헷갈리게 만들 뿐이라 지웠다 — 되살리려면 소비처부터 만들 것.
        """
        cfg = _load_repo_config()
        assert not hasattr(cfg, "UDS_MAX_ITEMS_PER_CATEGORY")
        assert hasattr(cfg, "UDS_MAX_FUNCTION_ITEMS")

    def test_uds_declares_its_caps(self):
        """UDS 도 상한을 공시하고, 이제 **요청으로 조정한다**.

        이력: `caps={}` → 화면이 절단을 말할 수 없었다 → 공시는 하되
        `api: None`(조정 불가) → 이제 `Form(None)` 으로 받는다. 마지막 단계에서
        `api` 는 **`Form(None)` 의 실효 기본값**이라 생성기 기본과 같아야 한다
        (`test_docgen_cap_wiring_parity::test_every_adjustable_cap_matches_handler`
        가 그 규약을 강제한다).
        """
        from backend.services.docgen_requirements import requirements_for
        caps = requirements_for("uds").get("caps") or {}
        assert set(caps) == {"max_source_files", "max_items_per_category"}
        for key, cap in caps.items():
            assert cap["effect"].strip(), f"{key}: 잘리면 무슨 일이 나는지 적혀 있어야 한다"
            assert cap["adjustable"] is True, f"{key}: 요청으로 조정할 수 있어야 한다"
            assert cap["api"] == cap["generator"], (
                f"{key}: Form(None) 이라 실효 기본값은 생성기 기본과 같아야 한다")
            assert isinstance(cap["generator"], int) and cap["generator"] > 0
            # 기본값의 출처는 계속 밝힌다 — 조정 가능해졌다고 이 정보가 사라지면
            # 화면의 "기본 1200" 이 어디서 온 수인지 알 수 없다.
            assert cap["env"].startswith("DEVOPS_UDS_"), key

    def test_declared_caps_track_config_not_a_copy(self):
        """공시값은 `config` 를 읽어야 한다 — 숫자를 복제하면 실제와 갈린다."""
        import config
        from backend.services.docgen_requirements import requirements_for
        caps = requirements_for("uds")["caps"]
        assert caps["max_source_files"]["generator"] == config.UDS_MAX_SOURCE_FILES
        assert caps["max_items_per_category"]["generator"] == config.UDS_MAX_FUNCTION_ITEMS


# --------------------------------------------------------------------------
# 5. 산출물 충실도 — 게이트는 payload 를 보고, 이 축은 **문서에 들어간 수**를 본다.
#
#    실측(2026-08-24, `reports/quality.sqlite` ⋈ gen_stats sidecar):
#      run 660·661 = 문서 반영 0/5(빈 heading 419) 인데 gate PASS · 점수 100.0
#      run 674     = 252/350(72.0%), 미반영 98      인데 gate PASS · 점수 99.5
#    즉 payload 가 완벽하면 문서가 비어 있어도 만점이 나왔다. 판정은 바꾸지 않고
#    (템플릿이 의도된 부분집합일 수 있다) 수치를 같은 자리에 나란히 남긴다.
# --------------------------------------------------------------------------
def _write_sidecar(tmp_path, **stats):
    from report_gen.docx_builder import gen_stats_path
    out = tmp_path / "uds.docx"
    gen_stats_path(str(out)).write_text(json.dumps(stats), encoding="utf-8")
    return out


class TestArtifactFidelityDoesNotFabricate:
    def test_no_sidecar_is_unmeasured_not_zero(self, tmp_path):
        """sidecar 부재는 **미측정**이다. 0% 로 적으면 재본 적 없는 실행이 최악값이 된다."""
        f = _uds_artifact_fidelity(tmp_path / "absent.docx")
        assert f["measured"] is False
        assert f["rates"] == {}, "미측정인데 비율을 지어냈다"
        assert "counts" not in f
        assert f["meta"]["artifact_fidelity"]["reason"] == "sidecar 없음"

    @pytest.mark.parametrize("payload", [0, None, "350", -3])
    def test_bad_denominator_is_unmeasured(self, tmp_path, payload):
        """분모가 없거나 수치가 아니면 대조 불가 — 통과로 접지 않는다."""
        out = _write_sidecar(tmp_path, payload_functions=payload, matched_functions=0)
        f = _uds_artifact_fidelity(out)
        assert f["measured"] is False and f["rates"] == {}
        assert "분모 없음" in f["meta"]["artifact_fidelity"]["reason"]

    def test_missing_numerator_is_unmeasured(self, tmp_path):
        """분자가 없으면(라이터가 안 셌으면) 100% 도 0% 도 아니다."""
        out = _write_sidecar(tmp_path, payload_functions=350)
        assert _uds_artifact_fidelity(out)["measured"] is False

    def test_measured_rate_matches_the_real_run_674(self, tmp_path):
        """실측 run 674 를 그대로 재현한다 — 252/350 = 72.0%."""
        out = _write_sidecar(tmp_path, payload_functions=350, matched_functions=252,
                             unmatched_payload_count=98, empty_heading_count=149)
        f = _uds_artifact_fidelity(out)
        assert f["rates"]["artifact_match_fill"] == 72.0
        assert "counts" not in f, (
            "원시 건수는 meta 로만 낸다 — recorder 가 counts 에서 읽는 건 "
            "total_functions 하나뿐이라 나머지는 죽은 쓰기가 된다"
        )
        af = f["meta"]["artifact_fidelity"]
        assert af["write_back_passed"] is False
        assert af["unmatched_payload_count"] == 98
        assert any("-98" in m for m in af["mismatches"]), af["mismatches"]

    def test_empty_document_is_zero_percent_not_silence(self, tmp_path):
        """실측 run 660/661 — payload 5개 중 0개. 0.0 이 **기록되어야** 한다."""
        out = _write_sidecar(tmp_path, payload_functions=5, matched_functions=0,
                             empty_heading_count=419)
        f = _uds_artifact_fidelity(out)
        assert f["measured"] is True and f["rates"]["artifact_match_fill"] == 0.0

    def test_full_reflection_passes_the_write_back_check(self, tmp_path):
        """음성 대조군 — 전부 반영되면 불일치가 **없어야** 한다.
        이걸 확인하지 않으면 '항상 경고' 코드도 위 테스트들을 통과한다."""
        out = _write_sidecar(tmp_path, payload_functions=350, matched_functions=350)
        af = _uds_artifact_fidelity(out)["meta"]["artifact_fidelity"]
        assert af["write_back_passed"] is True and af["mismatches"] == []


class TestFidelityInjection:
    def _measured(self):
        return {"measured": True, "rates": {"artifact_match_fill": 72.0}, "meta": {}}

    def test_wrapped_shape_gets_the_rate(self):
        qg = {"rates": {"input_fill": 98.3}, "counts": {"total_functions": 350}}
        out = _with_artifact_fidelity({"quick_gate": qg}, self._measured())
        assert out["quick_gate"]["rates"]["artifact_match_fill"] == 72.0
        assert out["quick_gate"]["rates"]["input_fill"] == 98.3, "기존 축을 지웠다"
        assert out["quick_gate"]["counts"] == {"total_functions": 350}, "counts 를 건드렸다"

    def test_bare_shape_gets_the_rate(self):
        """bare quick_gate(경로 3곳)도 같은 대접을 받아야 한다."""
        out = _with_artifact_fidelity({"rates": {"input_fill": 98.3}}, self._measured())
        assert out["rates"]["artifact_match_fill"] == 72.0

    def test_original_is_not_mutated(self):
        """호출부(local.py)는 같은 dict 를 API 응답으로도 돌려준다 — 제자리 수정 금지."""
        qg = {"rates": {"input_fill": 98.3}, "counts": {"total_functions": 350}}
        src = {"quick_gate": qg}
        out = _with_artifact_fidelity(src, self._measured())
        assert qg["rates"] == {"input_fill": 98.3}, "원본 rates 를 건드렸다"
        assert qg["counts"] == {"total_functions": 350}, "원본 counts 를 건드렸다"
        assert out["quick_gate"] is not qg, "사본이 아니라 같은 객체다"

    def test_unmeasured_injects_nothing(self):
        """미측정이면 **아무것도 달라지지 않아야** 한다. `artifact_match_fill` 부재만
        보면, 빈 `rates`/`counts` 를 새로 만드는 변경이 그대로 살아남는다."""
        unmeasured = {"measured": False, "rates": {}, "meta": {}}
        src = {"quick_gate": {"rates": {"input_fill": 98.3}, "counts": {"total_functions": 350}}}
        assert _with_artifact_fidelity(src, unmeasured) == src
        assert _with_artifact_fidelity({"rates": {"input_fill": 98.3}}, unmeasured) == {
            "rates": {"input_fill": 98.3}
        }

    def test_measured_flag_is_the_authority_not_the_rates_dict(self):
        """주입 여부는 **`measured` 가 정한다** — `rates` 가 비었는지로 정하지 않는다.

        지금은 미측정이면 `rates` 도 비어서 두 판단이 같은 답을 낸다. 그래서 조기반환을
        지워도 값은 안 변한다(뮤테이션 M5 생존). 하지만 그건 우연이고, 생산자가 진단용
        부분값을 `measured=False` 인 채 실으면 그 순간 갈린다. 권위를 한쪽으로 못박는다.
        """
        inconsistent = {"measured": False,
                        "rates": {"artifact_match_fill": 42.0}, "meta": {}}
        out = _with_artifact_fidelity({"rates": {"input_fill": 98.3}}, inconsistent)
        assert out == {"rates": {"input_fill": 98.3}}, (
            "measured=False 인데 rates 가 비어 있지 않다는 이유로 실렸다"
        )


class TestGatewayWiring:
    """관문이 **충실도와 인자를 실제로 이어붙이는지**. 조각별 테스트는 이걸 못 본다 —
    `_record_uds_run` 이 `_uds_artifact_fidelity` 호출을 통째로 빼도 위 테스트는 전부
    통과한다(각 조각은 여전히 옳게 동작하므로)."""

    def test_fidelity_reaches_both_the_metrics_and_the_meta(self, tmp_path, monkeypatch):
        from backend.helpers import uds as uds_mod
        out = _write_sidecar(tmp_path, payload_functions=350, matched_functions=252,
                             unmatched_payload_count=98)
        seen = {}

        def _fake_record(quality_eval, **kwargs):
            seen["eval"], seen["kwargs"] = quality_eval, kwargs
            return 1

        monkeypatch.setattr("workflow.quality.recorder.record_uds_run", _fake_record)
        qg = {"rates": {"input_fill": 98.3}, "counts": {"total_functions": 350}}
        uds_mod._record_uds_run(qg, source_root="D:/src", out_path=out,
                                ai_used=False, extra_meta={"entry": "test"})

        assert seen["eval"]["rates"]["artifact_match_fill"] == 72.0, "지표로 안 갔다"
        af = seen["kwargs"]["meta"]["artifact_fidelity"]
        assert af["matched_functions"] == 252 and af["unmatched_payload_count"] == 98
        assert af["write_back_passed"] is False
        assert seen["kwargs"]["meta"]["entry"] == "test", "호출부 meta 를 덮어썼다"
        assert seen["kwargs"]["output_path"] == str(out)
        assert "artifact_match_fill" not in qg["rates"], "호출부 dict 를 제자리 수정했다"

    def test_missing_sidecar_records_unmeasured_not_a_zero(self, tmp_path, monkeypatch):
        """음성 대조군 — sidecar 가 없으면 meta 는 미측정, 지표는 부재여야 한다."""
        seen = {}
        monkeypatch.setattr(
            "workflow.quality.recorder.record_uds_run",
            lambda quality_eval, **kw: seen.update(eval=quality_eval, kwargs=kw) or 1,
        )
        from backend.helpers import uds as uds_mod
        uds_mod._record_uds_run({"rates": {}, "counts": {"total_functions": 350}},
                                source_root="", out_path=tmp_path / "none.docx")
        assert seen["kwargs"]["meta"]["artifact_fidelity"]["measured"] is False
        assert "artifact_match_fill" not in seen["eval"]["rates"]
        assert evaluate_uds({"quick_gate": seen["eval"]}) is not None
        assert not [m for m in evaluate_uds({"quick_gate": seen["eval"]})
                    if m["metric_name"] == "artifact_match_pct"]


class TestFidelityMetricBoundary:
    def _rates(self, **extra):
        r = {k: 100.0 for k in ("called_fill", "calling_fill", "input_fill", "output_fill",
                                "description_fill", "asil_fill", "related_fill")}
        r.update(extra)
        return {"quick_gate": {"rates": r, "counts": {"total_functions": 350}}}

    def _named(self, metrics, name):
        return next((m for m in metrics if m["metric_name"] == name), None)

    def test_metric_absent_when_unmeasured(self):
        """⚠ 핵심 — 키가 없으면 `_rate_val` 이 0.0 을 준다. 그걸 기록하면 미측정이
        '반영률 0%' 로 둔갑한다. 지표 행 자체가 없어야 한다."""
        assert self._named(evaluate_uds(self._rates()), "artifact_match_pct") is None

    def test_metric_present_when_measured(self):
        m = self._named(evaluate_uds(self._rates(artifact_match_fill=72.0)), "artifact_match_pct")
        assert m is not None and m["value"] == 72.0

    def test_metric_is_not_gated(self):
        """threshold 를 붙이면 지금 판정에 들어가 대량 오탐이 된다(의도적 비게이트)."""
        m = self._named(evaluate_uds(self._rates(artifact_match_fill=0.0)), "artifact_match_pct")
        assert m["threshold"] is None and m["gate_pass"] is None

    def test_verdict_unchanged_by_the_new_axis(self):
        """음성 대조군 — 반영률 0% 여도 게이트 판정과 게이트 축 수는 그대로다."""
        without = evaluate_uds(self._rates())
        with_ = evaluate_uds(self._rates(artifact_match_fill=0.0))
        v0, v1 = compute_gate_verdict(without), compute_gate_verdict(with_)
        assert (v0["gate_pass"], v0["gated_count"]) == (v1["gate_pass"], v1["gated_count"])
        assert v1["gated_count"] == 7, "게이트 축은 7개 그대로여야 한다"


class TestAdvisorLabelRegistry:
    """`_UDS_ADVICE` 는 발화 규칙이자 **라벨 정본**이다(`flow_emit_pct` 선례).
    비게이트 축도 여기 등록해 두어야 임계를 정할 때 한 곳만 보면 된다."""

    def _rule(self):
        from workflow.quality.advisor import _UDS_ADVICE
        return _UDS_ADVICE["artifact_match_pct"]

    def test_axis_is_registered_with_a_label(self):
        r = self._rule()
        assert r["label"].strip() and r["low_advice"].strip()

    def test_axis_stays_non_gated_in_the_advisor_too(self):
        """⚠ 여기에 임계를 적으면 evaluator 가 비게이트로 둔 축에 제안이 발화한다 —
        판정 주체가 둘로 갈린다. 임계는 베이스라인(P2-2) 뒤에 **한 곳에서** 정한다."""
        assert self._rule()["threshold"] is None

    def test_no_suggestion_fires_without_a_threshold(self):
        """행동 단언 — 구조만 보면 발화 로직이 바뀐 걸 못 본다.
        DB threshold 도 rule threshold 도 없으면 제안 목록에 안 들어가야 한다."""
        from workflow.quality.advisor import _UDS_ADVICE
        rule = _UDS_ADVICE["artifact_match_pct"]
        score_threshold = None          # evaluator 가 threshold=None 으로 저장한다
        assert not (score_threshold is not None or rule.get("threshold") is not None), (
            "둘 중 하나라도 있으면 advisor 가 이 축으로 제안을 만든다"
        )
