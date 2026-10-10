from __future__ import annotations


def _register(tmp_path, monkeypatch, scm_type="git"):
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry

    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="x",
            name="X",
            scm_type=scm_type,
            source_root=str(tmp_path / "src"),
        )
    )
    return scm_registry


def test_use_manual_only_skips_scm_fallback(tmp_path, monkeypatch):
    """use_manual_only=True면 빈 manual이어도 로컬 SCM diff로 되돌아가지 않는다."""
    from workflow import change_trigger

    _register(tmp_path, monkeypatch)
    calls = {"n": 0}

    def _spy(*_a, **_k):
        calls["n"] += 1
        return ["SHOULD_NOT_USE.c"]

    monkeypatch.setattr(change_trigger, "get_changed_files", _spy)

    trig = change_trigger.build_registry_trigger(
        trigger_type="jenkins", scm_id="x", manual_changed_files=[], use_manual_only=True,
    )
    assert trig.changed_files == []
    assert calls["n"] == 0  # SCM diff 미호출


def test_use_manual_only_uses_provided_files(tmp_path, monkeypatch):
    from workflow import change_trigger

    _register(tmp_path, monkeypatch)
    monkeypatch.setattr(change_trigger, "get_changed_files", lambda *a, **k: ["SHOULD_NOT_USE.c"])

    trig = change_trigger.build_registry_trigger(
        trigger_type="jenkins", scm_id="x",
        manual_changed_files=["a.c", "b.h"], use_manual_only=True,
    )
    assert trig.changed_files == ["a.c", "b.h"]


def test_default_falls_back_to_scm_diff(tmp_path, monkeypatch):
    """use_manual_only 미지정(기본) + manual 없음 → 기존 로컬 SCM diff 폴백 유지."""
    from workflow import change_trigger

    _register(tmp_path, monkeypatch)
    monkeypatch.setattr(change_trigger, "get_changed_files", lambda *a, **k: ["diff.c"])

    trig = change_trigger.build_registry_trigger(trigger_type="local", scm_id="x")
    assert trig.changed_files == ["diff.c"]
