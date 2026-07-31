"""저장소 `docs/` SDS 폴백이 발동하면 **알려야** 한다.

세 생성기(`sts`/`suts`/`sits`)에는 `sds_map` 인자가 없을 때 저장소 `docs/` 를 글롭하는
폴백이 있다. 이건 **프로젝트 무관**이다 — `generators/sts.py` 자신의 docstring 이 적어
놓은 실측: *요구-함수 링크 5,992건이 100% 이 폴백에서 나왔고(끄면 0/63), 요구 ID는
프로젝트 간 네임스페이스가 겹쳐 오매핑이 걸러지지도 않는다.*

그런데 `sts`·`suts` 는 **런타임에 아무 말도 하지 않았다**(`sits` 만 로그를 남겼다).
다른 프로젝트 설계서로 요구-함수 매핑 전량이 만들어져도 로그 한 줄이 없던 것이다.

⚠ 폴백 **자체**를 없애지는 않는다 — 저장소 동봉 HDPDM01 샘플 데모가 이걸로 돈다.
없애는 게 아니라 **보이게** 만든다.
"""
from __future__ import annotations

import logging

import pytest

MODULES = ["sts", "suts", "sits"]


def _fresh(name, monkeypatch):
    """캐시를 비워 폴백이 실제로 다시 돌게 한다(모듈 전역 캐시라 테스트 간 누설)."""
    mod = __import__(f"generators.{name}", fromlist=["_load_default_sds_map"])
    monkeypatch.setattr(mod, "_SDS_MAP_CACHE", None, raising=False)
    if hasattr(mod, "_SDS_MAP_CACHE_MTIME"):
        monkeypatch.setattr(mod, "_SDS_MAP_CACHE_MTIME", None, raising=False)
    return mod


@pytest.mark.parametrize("name", MODULES)
def test_fallback_announces_itself(name, monkeypatch, caplog):
    """폴백이 엔트리를 내놓으면 어느 문서를 썼는지 로그에 남는다."""
    mod = _fresh(name, monkeypatch)
    monkeypatch.setattr(mod, "_extract_sds_partition_map",
                        lambda p: {"motorctrl": {"related": "SwTR_0001", "asil": "A",
                                                 "description": "x"}},
                        raising=False)
    if name == "sits":   # sits 는 함수 안에서 import 한다
        import report_gen.requirements as rr
        monkeypatch.setattr(rr, "_extract_sds_partition_map",
                            lambda p: {"motorctrl": {"related": "SwTR_0001", "asil": "A"}})
    with caplog.at_level(logging.INFO):
        out = mod._load_default_sds_map()
    if not out:
        pytest.skip("저장소 docs/ 에 SDS 문서가 없어 폴백이 비었다")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert joined.strip(), f"{name}: 폴백이 값을 냈는데 로그가 없다"
    assert "docs" in joined or "SDS" in joined, f"{name}: 출처를 안 밝힌다 — {joined[:120]}"


@pytest.mark.parametrize("name", ["sts", "suts"])
def test_warning_level_for_project_agnostic_source(name, monkeypatch, caplog):
    """요구-함수 매핑·ASIL 을 좌우하므로 INFO 가 아니라 WARNING 이어야 한다."""
    mod = _fresh(name, monkeypatch)
    monkeypatch.setattr(mod, "_extract_sds_partition_map",
                        lambda p: {"motorctrl": {"related": "SwTR_0001", "asil": "A",
                                                 "description": "x"}},
                        raising=False)
    with caplog.at_level(logging.DEBUG):
        out = mod._load_default_sds_map()
    if not out:
        pytest.skip("저장소 docs/ 에 SDS 문서가 없어 폴백이 비었다")
    assert any(r.levelno >= logging.WARNING for r in caplog.records), \
        f"{name}: 프로젝트 무관 출처인데 WARNING 이 없다"


@pytest.mark.parametrize("name", MODULES)
def test_fallback_still_returns_data(name, monkeypatch):
    """경고를 붙이면서 폴백 **기능**을 죽이지 않았는지 — 동봉 샘플 데모가 이걸로 돈다."""
    mod = _fresh(name, monkeypatch)
    out = mod._load_default_sds_map()
    assert isinstance(out, dict)


def test_sds_file_selection_uses_shared_classifier():
    """폴백의 파일 선별도 공용 판정이어야 `SwDS` 표기를 놓치지 않는다."""
    import inspect

    from generators import sits, sts, suts
    for mod in (sts, suts, sits):
        src = inspect.getsource(mod._load_default_sds_map)
        assert "is_sds_filename" in src, f"{mod.__name__}: 공용 판정을 안 쓴다"
