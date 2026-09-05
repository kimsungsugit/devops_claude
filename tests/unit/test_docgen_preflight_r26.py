"""준비 게이트 R26 — 조치 버튼 400 · 통합 Summary 영구 차단 · 모름→차단 접기.

2026-09-03 감사(P-1~P-3)가 찾은 것을 회귀로 고정한다. 셋 다 "게이트가 **사실**을
재는가" 의 결함이다:

- P-1 대표 조치 버튼([이 파일로 교체])이 `400 알 수 없는 문서 키: swrs` 였다 — 액션에
  레지스트리 키(`target`)가 없어 보드가 입력 키(`step.id`)를 그대로 보냈다.
- P-2 통합 Summary 의 유일한 `required` 입력을 게이트가 한 번도 채우지 않아 **영구
  `진행 불가`** 였다 — 라우터는 요청의 `source_paths` 를 읽고 비면 양식 자체로 진행한다.
- P-3 config 를 못 읽으면 "설정에 없다"(missing) 로, 확인 실패를 "확인했고 없음"(False)
  으로, 허용 prefix 밖 경로를 "워커를 실행하세요" 로 접었다.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import docgen_preflight as pf
from backend.schemas import ScmLinkedDocs, SwReportBuildRequest
from backend.services import docgen_requirements as req
from backend.services import file_resolver as fr
from backend.services import scm_registry as reg
from backend.services import swut_meta_resolver as meta

client = TestClient(app)
HEADERS = {"X-User": "tester"}


def _post(payload: dict) -> dict:
    r = client.post("/api/docgen/preflight", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    return r.json()


def _step(data: dict, step_id: str) -> dict | None:
    return next((s for s in data["steps"] if s["id"] == step_id), None)


def _entry(tmp_path: Path, **linked: str):
    """레지스트리 entry 흉내 — `linked_docs.model_dump` 와 `source_root` 만 있으면 된다."""
    return SimpleNamespace(
        linked_docs=ScmLinkedDocs(**linked),
        source_root=str(tmp_path),
        builder_project_id="",
    )


def _adopt_actions(step: dict) -> list[dict]:
    return [a for a in (step.get("actions") or []) if a.get("kind") == "adopt_suggestion"]


# ── P-1: 조치 액션은 레지스트리 키(`target`)를 싣는다 ─────────────────────────

def test_stale_registry_srs_carries_registry_target(tmp_path: Path, monkeypatch) -> None:
    """레지스트리에서 온 낡은 SRS 경로 → 액션 `target` 이 **레지스트리 키** `srs` 다.

    화면은 `step.id`(입력 키 `swrs`)만 알고 `adopt-doc-path` 는 `srs` 만 받는다 — 이 값이
    없던 동안 대표 조치 버튼이 400 이었다.
    """
    old = tmp_path / "SwRS_v2.03.docx"                       # 등록됐지만 부재
    (tmp_path / "SwRS_v3.01_R.docx").write_bytes(b"x")     # 같은 폴더의 개정본
    monkeypatch.setattr(reg, "get_registry_entry", lambda _id: _entry(tmp_path, srs=str(old)))

    data = _post({"doc_type": "uds", "scm_id": "t"})
    step = _step(data, req.IN_SWRS)
    assert step is not None and step["state"] == "stale_path", step
    adopt = _adopt_actions(step)
    assert adopt, "개정본이 실재하는데 채택 액션이 없다"
    assert adopt[0]["target"] == "srs", adopt
    assert adopt[0]["value"] == "SwRS_v3.01_R.docx"


def test_stale_registry_template_targets_the_doc_specific_key(tmp_path: Path, monkeypatch) -> None:
    """템플릿은 문서별 레지스트리 키(`uds_template`)가 target 이다 — 공용 `template` 이 아니다."""
    wrong = tmp_path / "unit.xlsm"                            # UDS 는 .docx 를 연다
    wrong.write_bytes(b"x")
    (tmp_path / "unit.docx").write_bytes(b"x")
    monkeypatch.setattr(reg, "get_registry_entry",
                        lambda _id: _entry(tmp_path, uds_template=str(wrong)))

    data = _post({"doc_type": "uds", "scm_id": "t"})
    step = _step(data, req.IN_TEMPLATE)
    assert step is not None and step["state"] == "stale_path", step
    adopt = _adopt_actions(step)
    assert adopt and adopt[0]["target"] == "uds_template", adopt


def test_stale_settings_path_is_not_offered_for_registry_adoption(tmp_path: Path) -> None:
    """설정(doc_paths)에서 온 경로는 레지스트리 교체 대상이 **아니다**.

    교체해도 설정이 레지스트리를 계속 가려 화면은 그대로다 — 그러면 "교체했습니다" 토스트가
    거짓이 된다. 어디서 바꿔야 하는지를 사유로 말한다.
    """
    old = tmp_path / "SwRS_v2.03.docx"
    (tmp_path / "SwRS_v3.01_R.docx").write_bytes(b"x")
    data = _post({"doc_type": "uds", "source_root": str(tmp_path),
                  "doc_paths": {"srs": str(old)}})
    step = _step(data, req.IN_SWRS)
    assert step is not None and step["state"] == "stale_path", step
    assert not _adopt_actions(step), "설정 경로에 레지스트리 채택을 권했다"
    assert any(a.get("kind") == "pick_path" for a in step.get("actions") or [])
    assert "설정" in step.get("reason", "")


def test_every_adopt_action_targets_a_real_registry_field(tmp_path: Path, monkeypatch) -> None:
    """게이트가 내는 **모든** 채택 액션의 `target` 은 `ScmLinkedDocs` 의 실제 필드여야 한다.

    한 자리에서만 고치면 다른 자리(템플릿 확장자 불일치 가지)가 옛 계약으로 남는다.
    """
    old_srs = tmp_path / "SwRS_v2.03.docx"
    (tmp_path / "SwRS_v3.01_R.docx").write_bytes(b"x")
    wrong_tpl = tmp_path / "unit.xlsm"
    wrong_tpl.write_bytes(b"x")
    (tmp_path / "unit.docx").write_bytes(b"x")
    monkeypatch.setattr(reg, "get_registry_entry",
                        lambda _id: _entry(tmp_path, srs=str(old_srs), uds_template=str(wrong_tpl)))
    data = _post({"doc_type": "uds", "scm_id": "t"})
    seen = 0
    for s in data["steps"]:
        for a in _adopt_actions(s):
            seen += 1
            assert a.get("target") in ScmLinkedDocs.model_fields, (s["id"], a)
            assert a.get("target") in pf._ADOPTABLE_DOC_KEYS, (s["id"], a)
    assert seen >= 2, "두 가지(파일 부재·형식 불일치)를 다 밟아야 한다"


def test_adoptable_keys_are_registry_fields_and_exclude_shared_template() -> None:
    """화이트리스트 ⊆ 스키마 필드. 공용 `template` 은 `ScmLinkedDocs` 에 없으므로 빠진다.

    예전 화이트리스트는 `template` 을 통과시키고 `:1926` 에서 "기존 등록 경로가 없습니다"
    로만 끝냈다 — 통과하는 척하는 죽은 키였다.
    """
    assert pf._ADOPTABLE_DOC_KEYS <= set(ScmLinkedDocs.model_fields)
    assert "template" not in pf._ADOPTABLE_DOC_KEYS
    assert {"srs", "sds", "uds", "hsis", "stp", "uds_template"} <= pf._ADOPTABLE_DOC_KEYS
    # ⚠ 전부 **문자열 필드**여야 한다. `vectorcast`/`codesonar` 같은 `List[str]` 필드가
    #   들어오면 엔드포인트의 리스트 분기(`[new_path, *current[1:]]`)가 열린다(리뷰 I4).
    for k in pf._ADOPTABLE_DOC_KEYS:
        assert ScmLinkedDocs.model_fields[k].annotation is str, (k, ScmLinkedDocs.model_fields[k].annotation)


# ── P-2: 통합 Summary — 레벨별 산출물은 폼(`source_paths`)에서 온다 ──────────────

def test_swreport_level_artifacts_are_optional_not_required() -> None:
    """`required` 로 두고 아무 데서도 안 채우면 게이트가 **영구 진행 불가**를 낸다."""
    spec = req.requirements_for("swreport")
    assert req.IN_LEVEL_ARTIFACTS not in spec["required"]
    assert spec["optional"].get(req.IN_LEVEL_ARTIFACTS, "").strip(), "없으면 무슨 일이 생기는지 말해야 한다"


def test_swreport_without_source_paths_is_needed_not_blocked() -> None:
    data = _post({"doc_type": "swreport", "form": {"project_id": "KJPDS02"}})
    step = _step(data, req.IN_LEVEL_ARTIFACTS)
    assert step is not None, "레벨별 산출물 행이 없다"
    assert step["state"] == "needed", step
    assert not step.get("required"), "선택 입력이 required 로 나갔다"
    assert step.get("effect")


def test_swreport_reads_source_paths_from_the_form_like_the_router(tmp_path: Path) -> None:
    """라우터(`SwReportBuildRequest.source_paths`)와 **같은 키·같은 목록 함수**를 본다.

    라우터는 목록을 **전부** `read_bytes` 하므로 하나라도 없으면 빌드가 500 이다 — 부분
    결손(`degraded`)이 아니라 **차단**이어야 한다(R26 리뷰 C1: 처음엔 degraded 로 냈고
    그건 게이트가 "진행해도 된다" 고 한 조건에서 생성이 죽는 계약이었다).
    """
    from backend.routers.swreport import planned_source_paths
    assert "source_paths" in SwReportBuildRequest.model_fields, "라우터 필드명이 바뀌었다 — 게이트도 같이"
    ok = tmp_path / "SwUTCR.xlsm"
    ok.write_bytes(b"x")
    gone = tmp_path / "SwITCR.xlsm"
    raw = [str(ok), "", str(gone)]
    assert planned_source_paths(raw) == [str(ok), str(gone)], "라우터가 읽을 목록과 다르다"
    data = _post({"doc_type": "swreport",
                  "form": {"project_id": "KJPDS02", "source_paths": raw}})
    step = _step(data, req.IN_LEVEL_ARTIFACTS)
    assert step is not None and step["state"] == "missing", step
    assert step["required"] is True, "지정한 목록이 깨졌는데 선택 입력으로 넘어간다"
    assert step["measured"] == {"folders": 2, "missing": 1, "unknown": 0}
    assert "SwITCR.xlsm" in step["reason"] and "실패" in step["reason"]
    assert data["verdict"] == "blocked"

    data2 = _post({"doc_type": "swreport",
                   "form": {"project_id": "KJPDS02", "source_paths": [str(ok)]}})
    assert _step(data2, req.IN_LEVEL_ARTIFACTS)["state"] == "ok"


def test_swreport_single_missing_artifact_still_blocks(tmp_path: Path) -> None:
    """항목이 **1개**여도 깨진 목록은 차단이다.

    리뷰 확인 패스가 잡았다 — 1개짜리 목록이 단일 경로 분기로 빠져 `required` 승격이 없었고,
    게이트는 `준비 완료` 인데 라우터는 `FileNotFoundError` 였다.
    """
    gone = tmp_path / "SwUTCR.xlsm"
    data = _post({"doc_type": "swreport",
                  "form": {"project_id": "KJPDS02", "source_paths": [str(gone)]}})
    step = _step(data, req.IN_LEVEL_ARTIFACTS)
    assert step is not None and step["state"] == "missing", step
    assert step["required"] is True, step
    assert data["verdict"] == "blocked"


def test_swreport_path_with_a_comma_is_not_split(tmp_path: Path) -> None:
    """콤마가 든 경로(`…\\Report,APP\\x.xlsm` 실측)를 두 조각으로 오분할하지 않는다(리뷰 W1)."""
    folder = tmp_path / "Report,APP"
    folder.mkdir()
    ok = folder / "SwUTCR.xlsm"
    ok.write_bytes(b"x")
    data = _post({"doc_type": "swreport",
                  "form": {"project_id": "KJPDS02", "source_paths": [str(ok)]}})
    step = _step(data, req.IN_LEVEL_ARTIFACTS)
    assert step is not None and step["state"] == "ok", step


def test_swreport_single_string_source_path_is_not_silently_dropped(tmp_path: Path) -> None:
    ok = tmp_path / "SwUTCR.xlsm"
    ok.write_bytes(b"x")
    data = _post({"doc_type": "swreport",
                  "form": {"project_id": "KJPDS02", "source_paths": str(ok)}})
    assert _step(data, req.IN_LEVEL_ARTIFACTS)["state"] == "ok"


# ── P-3: 모름은 모름이다 ───────────────────────────────────────────────────────

def test_unreadable_meta_config_is_unmeasured_not_missing(monkeypatch) -> None:
    """양식 설정 파일을 **못 읽은** 것은 "설정에 없다" 가 아니다.

    예전엔 `{}` 로 접어 required 행이 `missing` → **진행 불가**였다 — 파일이 깨진 순간
    시험 결과 6종이 전부 막혔고, 사람은 등록을 다시 하러 갔다.
    """
    def _boom(_pid: str):
        raise meta.MetaConfigUnreadable("config/swut_meta.json: JSONDecodeError: boom")
    monkeypatch.setattr(meta, "load_meta_from_config_strict", _boom)

    data = _post({"doc_type": "swreport", "form": {"project_id": "KJPDS02"}})
    step = _step(data, "report_template")
    assert step is not None
    assert step["state"] == "unmeasured", step
    assert "읽지 못했습니다" in step.get("reason", "")
    assert data["verdict"] != "blocked"


def test_unreadable_meta_config_does_not_block_config_derived_inputs(monkeypatch) -> None:
    """VectorCAST 로그·규격서는 config 에서 오므로, config 를 못 읽으면 그 둘도 **모름**이다.

    ⚠ 값 로더 seam(`config_log_folders_for`)도 함께 갈아 끼운다 — 안 그러면 이 가드가
      머신의 실 `config/swut_meta.json` 내용에 의존한다(리뷰 W6).
    """
    def _boom(_pid: str):
        raise meta.MetaConfigUnreadable("swut_meta.json: PermissionError: locked")
    monkeypatch.setattr(meta, "load_meta_from_config_strict", _boom)
    monkeypatch.setattr(meta, "config_log_folders_for", lambda _pid, _s: [])
    monkeypatch.setattr(meta, "config_spec_path_for", lambda _pid, _s: "")

    data = _post({"doc_type": "swut", "form": {"project_id": "HDPDM01"}})
    vcast = _step(data, req.IN_VCAST)
    assert vcast is not None and vcast["state"] == "unmeasured", vcast
    assert _step(data, "meta_config") is not None, "왜 모르는지를 말하는 행이 없다"
    assert data["verdict"] != "blocked", data["verdict"]


def test_unmeasured_meta_config_is_a_real_loader_outcome(tmp_path: Path, monkeypatch) -> None:
    """strict 로더는 파일이 있는데 못 읽으면 예외, 없으면 `{}` 다 — 접지 않는다."""
    broken = tmp_path / "swut_meta.json"
    broken.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(meta, "_META_CONFIG_PATH", str(broken))
    with pytest.raises(meta.MetaConfigUnreadable):
        meta.load_meta_from_config_strict("KJPDS02")
    monkeypatch.setattr(meta, "_META_CONFIG_PATH", str(tmp_path / "absent.json"))
    assert meta.load_meta_from_config_strict("KJPDS02") == {}
    # 잘못된 바이트(UnicodeDecodeError)도 "못 읽음" 이다 — JSONDecodeError 만 잡으면 500 이 샌다(리뷰 W3).
    bad_bytes = tmp_path / "bad_bytes.json"
    bad_bytes.write_bytes(b"\xff\xfe{}")
    monkeypatch.setattr(meta, "_META_CONFIG_PATH", str(bad_bytes))
    with pytest.raises(meta.MetaConfigUnreadable):
        meta.load_meta_from_config_strict("KJPDS02")


def test_multi_path_input_with_an_unconfirmed_piece_is_unmeasured(tmp_path: Path, monkeypatch) -> None:
    """다중 경로(VectorCAST 폴더)도 조각 하나를 **못 확인**했으면 전체가 모름이다.

    예전엔 `bad == probes` 로 접혀 "하나도 찾지 못했습니다"(missing) → required → 진행 불가.
    단일 경로에서 없앤 접기가 옆 분기에 그대로 있었다(리뷰 C2).
    """
    good = tmp_path / "APP"
    good.mkdir()
    flaky = str(tmp_path / "BOOT")
    tpl = tmp_path / "sutr_template.xlsm"
    tpl.write_bytes(b"x")
    # 머신의 실 config 에 의존하지 않는다 — 양식도 로그 폴더도 seam 으로 준다.
    monkeypatch.setattr(meta, "load_meta_from_config_strict",
                        lambda _pid: {"template_paths": {"sutr_template": str(tpl)}})
    monkeypatch.setattr(meta, "config_log_folders_for",
                        lambda _pid, _s: [str(good), flaky])
    monkeypatch.setattr(meta, "config_spec_path_for", lambda _pid, _s: "")
    monkeypatch.setattr(meta, "config_spec_is_required_for", lambda _pid, _s: False)
    monkeypatch.setattr(fr, "get_resolver", lambda: _ExistsRaises(flaky, RuntimeError("ipc hiccup")))
    data = _post({"doc_type": "sutr", "form": {"project_id": "HDPDM01"}})
    step = _step(data, req.IN_VCAST)
    assert step is not None and step["state"] == "unmeasured", step
    assert step["measured"]["unknown"] == 1
    assert "확인하지 못했습니다" in step["reason"]
    assert data["verdict"] != "blocked", data["verdict"]


class _ExistsRaises:
    """`exists` 가 특정 경로에서 예외를 낸다 — IPC 가 흔들린 자리."""

    mode = "local"

    def __init__(self, bad: str, exc: Exception) -> None:
        self.bad, self.exc = bad, exc

    def exists(self, path: str) -> bool:
        if str(path) == self.bad:
            raise self.exc
        return Path(path).exists()

    def list_dir(self, path: str, pattern: str = "*", recursive: bool = False,
                 include_dirs: bool = False):
        return []


def test_unconfirmed_input_is_unknown_in_the_chain_not_false(tmp_path: Path, monkeypatch) -> None:
    """확인 실패는 사슬에서 `have=None`(모름)이다 — `False`(확인했고 없음)가 아니다.

    예전엔 `available[key] = (state == S_OK)` 라 IPC 가 한 번 흔들리면 사슬이 ✗ 로 그려졌다.
    같은 파일이 주석 커버리지에서 정확히 이 접기를 금지해 두고도 입력 행에서는 어겼다.
    """
    sds = "X:/nope/SwDS.docx"
    monkeypatch.setattr(fr, "get_resolver", lambda: _ExistsRaises(sds, RuntimeError("ipc hiccup")))
    data = _post({"doc_type": "uds", "source_root": str(tmp_path), "doc_paths": {"sds": sds}})
    sds_step = _step(data, req.IN_SWDS)
    assert sds_step is not None and sds_step["state"] == "unmeasured", sds_step
    chain = _step(data, "chain_asil")
    assert chain is not None
    rows = [r for r in chain["chain"] if r.get("input") == req.IN_SWDS]
    assert rows, "사슬에 SwDS 출처 행이 없다"
    assert all(r["have"] is None for r in rows), rows
    # 사슬 단계도 **전부** 모름이면 `unmeasured` 다 — "확보되지 않았다"(degraded) 로 단언하지
    # 않는다(리뷰 W5). ASIL 출처(comment/sds/srs/uds)를 전부 "확인 못 함" 으로 만든다 —
    # 경로가 아예 없는 입력은 False(확인했고 없음)가 맞으므로 세 경로를 다 준다.
    all_nope = {"sds": "X:/nope/SwDS.docx", "srs": "X:/nope/SwRS.docx", "uds": "X:/nope/SwUDS.docx"}

    class _AllRaise(_ExistsRaises):
        def exists(self, path: str) -> bool:
            if "nope" in str(path):
                raise RuntimeError("ipc hiccup")
            return Path(path).exists()
    monkeypatch.setattr(fr, "get_resolver", lambda: _AllRaise("__none__", RuntimeError()))
    data3 = _post({"doc_type": "uds", "source_root": str(tmp_path), "doc_paths": all_nope})
    chain3 = _step(data3, "chain_asil")
    assert chain3 is not None
    assert all(r["have"] is None for r in chain3["chain"] if r.get("grounded")), chain3["chain"]
    assert chain3["state"] == "unmeasured", chain3
    assert "확인하지 못했습니다" in chain3.get("reason", "")

    # 대조군 — 정말 없으면 False 다(모름과 없음을 같은 값으로 접지 않는다).
    monkeypatch.setattr(fr, "get_resolver", lambda: _ExistsRaises("__none__", RuntimeError()))
    data2 = _post({"doc_type": "uds", "source_root": str(tmp_path), "doc_paths": {"sds": sds}})
    rows2 = [r for r in _step(data2, "chain_asil")["chain"] if r.get("input") == req.IN_SWDS]
    assert rows2 and all(r["have"] is False for r in rows2), rows2


class _CloudiumDenies:
    """cloudium 모드에서 `exists` 가 PermissionError 를 낸다 — 문장만 다르다."""

    mode = "cloudium"

    def __init__(self, message: str) -> None:
        self.message = message

    def exists(self, path: str) -> bool:
        raise PermissionError(self.message)

    def list_dir(self, path: str, pattern: str = "*", recursive: bool = False,
                 include_dirs: bool = False):
        raise PermissionError(self.message)


_PREFIX_MSG = ("Cloudium 모드: allowed_prefixes 미설정 — workspace/home 외부 경로 차단됨: "
               "U:/other/SwRS.docx")
_WORKER_MSG = ("Cloudium worker 연결 실패 (127.0.0.1:8766): [WinError 10061]\n"
               "  'excel_rename_gui_v2.exe' 가 실행 중인지 확인하세요.")


_PREFIX_MSG_MAIN = "Cloudium 모드: 허용되지 않은 경로 접근 차단됨: U:/other/SwRS.docx"   # file_resolver.py:487


@pytest.mark.parametrize("message,kind", [
    (_PREFIX_MSG, "prefix"),
    (_PREFIX_MSG_MAIN, "prefix"),   # 허용목록이 **설정된** 채로 밖인 경우 — 실무의 주 경로
    (_WORKER_MSG, "worker"),
    ("Cloudium worker 미응답 — 127.0.0.1:8766.", "worker"),
    ("PermissionError: [Errno 13] Permission denied: 'U:/x'", "other"),
    ("Cloudium 모드는 read-only입니다. write_text 차단.", "other"),   # "차단" 만으로 prefix 가 아니다
])
def test_permission_error_kind(message: str, kind: str) -> None:
    assert pf._permission_error_kind(message) == kind


@pytest.mark.parametrize("message", [_PREFIX_MSG, _PREFIX_MSG_MAIN])
def test_prefix_block_is_not_reported_as_a_dead_worker(tmp_path: Path, monkeypatch, message: str) -> None:
    """허용 prefix 밖 경로는 워커가 죽은 게 아니다 — "워커를 실행하세요" 는 거짓 안내다."""
    monkeypatch.setattr(fr, "get_resolver", lambda: _CloudiumDenies(message))
    data = _post({"doc_type": "uds", "source_root": str(tmp_path),
                  "doc_paths": {"srs": "U:/other/SwRS.docx"}})
    assert _step(data, "worker") is None, "prefix 차단에 워커 실행 행이 떴다"
    srs = _step(data, req.IN_SWRS)
    assert srs is not None and srs["state"] == "error", srs
    assert "allowed_prefixes" in srs.get("reason", "")
    assert any(a.get("kind") == "open_scm" for a in srs.get("actions") or []), srs.get("actions")
    assert not any(a.get("kind") == "run_worker" for a in srs.get("actions") or [])


def test_dead_worker_still_gets_the_worker_row(tmp_path: Path, monkeypatch) -> None:
    """대조군 — 진짜 연결 실패는 여전히 워커 행 + 실행 안내다."""
    monkeypatch.setattr(fr, "get_resolver", lambda: _CloudiumDenies(_WORKER_MSG))
    data = _post({"doc_type": "uds", "source_root": str(tmp_path),
                  "doc_paths": {"srs": "U:/docs/SwRS.docx"}})
    worker = _step(data, "worker")
    assert worker is not None and worker["state"] == "error", worker
    assert any(a.get("kind") == "run_worker" for a in worker.get("actions") or [])
