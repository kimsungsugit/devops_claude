"""54차 T281 — swut_meta_resolver.py 회귀.

DRY 통합 모듈 — SwUT/SwIT 라우터 공통 path resolver + ASIL 매핑.
6 시나리오: req 우선 / config fallback / swuds path / c_source path /
apply_function_asil_map source origin / ASIL 충돌 warning.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import swut_meta_resolver as resolver  # noqa: E402


@pytest.fixture
def cfg_setup(tmp_path, monkeypatch):
    """공통 fixture — tmp_path에 swut_meta.json 생성 + resolver path patch."""
    def _make(cfg_dict):
        cfg_path = tmp_path / "swut_meta.json"
        cfg_path.write_text(json.dumps(cfg_dict), encoding="utf-8")
        monkeypatch.setattr(resolver, "_META_CONFIG_PATH", str(cfg_path))
        resolver._read_meta_config_raw.cache_clear()
        return cfg_path
    return _make


def _fake_req(**kwargs):
    """SimpleNamespace fake req — swuds_docx_path/c_source_root/project_id 등 속성."""
    defaults = {
        "swuds_docx_path": "",
        "c_source_root": "",
        "project_id": "HDPDM01",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestResolveSwudsPath:
    def test_req_priority(self, cfg_setup):
        cfg_setup({"projects": {"HDPDM01": {"swuds_docx_path": "U:/config.docx"}}})
        req = _fake_req(swuds_docx_path="D:/from_req.docx")
        assert resolver.resolve_swuds_path(req, "HDPDM01") == "D:/from_req.docx"

    def test_config_fallback(self, cfg_setup):
        cfg_setup({"projects": {"HDPDM01": {"swuds_docx_path": "U:/config.docx"}}})
        req = _fake_req(swuds_docx_path="")
        assert resolver.resolve_swuds_path(req, "HDPDM01") == "U:/config.docx"

    def test_both_empty(self, cfg_setup):
        cfg_setup({"projects": {"HDPDM01": {}}})
        req = _fake_req(swuds_docx_path="")
        assert resolver.resolve_swuds_path(req, "HDPDM01") == ""


class TestResolveCSourceRoot:
    def test_req_priority(self, cfg_setup):
        cfg_setup({"projects": {"HDPDM01": {"c_source_root": "C:/config_src"}}})
        req = _fake_req(c_source_root="D:/from_req_src")
        assert resolver.resolve_c_source_root(req, "HDPDM01") == "D:/from_req_src"

    def test_config_fallback(self, cfg_setup):
        cfg_setup({"projects": {"HDPDM01": {"c_source_root": "C:/config_src"}}})
        req = _fake_req(c_source_root="")
        assert resolver.resolve_c_source_root(req, "HDPDM01") == "C:/config_src"


class TestApplyFunctionAsilMap:
    """30차 W21 + 32차 W28 + 50차 W4/W5 정책."""

    def _session(self):
        from backend.services.swut_input_adapter import EnvironmentData, SwUTSession
        return SwUTSession(
            project_id="HDPDM01", version="v0.01",
            source_kind="log_folder", source_path="",
            environments=[EnvironmentData(env_name="SWTE_01")],
        )

    def test_records_source_origin_req(self, monkeypatch, cfg_setup):
        """c_source_root req 사용 시 source origin에 'req' 표기."""
        cfg_setup({"projects": {"HDPDM01": {}}})

        class FakeResult:
            warnings: list[str] = []
            function_asil_map = {"SwUFn_0101": "B"}

        import backend.services.swut_asil_resolver as asil_mod
        monkeypatch.setattr(
            asil_mod, "resolve_function_asil_map", lambda *_a, **_k: FakeResult(),
        )
        monkeypatch.setattr(
            resolver, "resolve_swuds_function_asil_map",
            lambda req, project_id: {},
        )
        req = _fake_req(c_source_root="C:/from_req_src")
        session = self._session()
        resolver.apply_function_asil_map(req, session, "HDPDM01")
        assert any("c_source 1건 (req)" in w for w in session.parse_warnings)

    def test_records_source_origin_config_fallback(self, monkeypatch, cfg_setup):
        """c_source_root req 비면 'config fallback' 표기."""
        cfg_setup({"projects": {"HDPDM01": {"c_source_root": "C:/from_config_src"}}})

        class FakeResult:
            warnings: list[str] = []
            function_asil_map = {"SwUFn_0101": "B"}

        import backend.services.swut_asil_resolver as asil_mod
        monkeypatch.setattr(
            asil_mod, "resolve_function_asil_map", lambda *_a, **_k: FakeResult(),
        )
        monkeypatch.setattr(
            resolver, "resolve_swuds_function_asil_map",
            lambda req, project_id: {},
        )
        req = _fake_req(c_source_root="")  # 비면 config fallback
        session = self._session()
        resolver.apply_function_asil_map(req, session, "HDPDM01")
        assert any("(config fallback)" in w for w in session.parse_warnings)

    def test_conflict_warning(self, monkeypatch, cfg_setup):
        """c_source ↔ SwUDS 충돌 시 parse_warnings에 사유 누적 + c_source 우선."""
        cfg_setup({"projects": {"HDPDM01": {}}})

        class FakeResult:
            warnings: list[str] = []
            function_asil_map = {"SwUFn_0101": "B"}

        import backend.services.swut_asil_resolver as asil_mod
        monkeypatch.setattr(
            asil_mod, "resolve_function_asil_map", lambda *_a, **_k: FakeResult(),
        )
        # 라운드 89: apply는 단일 parse seam resolve_swuds_maps 사용 (id→ASIL, name→id).
        # 2026-06-10: out_warnings kwarg 추가 — mock도 **kwargs 수용.
        monkeypatch.setattr(
            resolver, "resolve_swuds_maps",
            lambda req, project_id, **_kw: ({"SwUFn_0101": "D"}, {}),
        )
        req = _fake_req(c_source_root="C:/src", swuds_docx_path="C:/swuds.docx")
        session = self._session()
        resolver.apply_function_asil_map(req, session, "HDPDM01")
        assert session.environments[0].function_asil_map["SwUFn_0101"] == "B"
        assert any("ASIL 충돌" in w for w in session.parse_warnings)

    def test_both_empty_skips(self, cfg_setup):
        """req 둘 다 비고 config도 비면 silent skip."""
        cfg_setup({"projects": {"HDPDM01": {}}})
        req = _fake_req(c_source_root="", swuds_docx_path="")
        session = self._session()
        resolver.apply_function_asil_map(req, session, "HDPDM01")
        # function_asil_map default 빈 dict 유지
        assert session.environments[0].function_asil_map == {}


class TestResolveHmrHtmlPath:
    """60차 F6-C — HMR HTML path resolver 회귀."""

    def test_req_priority(self, cfg_setup):
        """req.hmr_html_path 우선."""
        cfg_setup({"projects": {"HDPDM01": {"hmr_html_path": "U:/config_hmr.html"}}})
        req = SimpleNamespace(hmr_html_path="D:/from_req_hmr.html", project_id="HDPDM01")
        assert resolver.resolve_hmr_html_path(req, "HDPDM01") == "D:/from_req_hmr.html"

    def test_config_fallback(self, cfg_setup):
        """req 비면 config fallback."""
        cfg_setup({"projects": {"HDPDM01": {"hmr_html_path": "U:/config_hmr.html"}}})
        req = SimpleNamespace(hmr_html_path="", project_id="HDPDM01")
        assert resolver.resolve_hmr_html_path(req, "HDPDM01") == "U:/config_hmr.html"

    def test_both_empty_returns_none_bytes(self, cfg_setup):
        """req + config 모두 비면 resolve_hmr_html_bytes는 None."""
        cfg_setup({"projects": {"HDPDM01": {}}})
        req = SimpleNamespace(hmr_html_path="", project_id="HDPDM01")
        assert resolver.resolve_hmr_html_bytes(req, "HDPDM01") is None

    def test_out_warnings_on_read_failure_f6_round1_w1(self, monkeypatch, cfg_setup):
        """F6 Round 1 W1 fix: read 실패 시 out_warnings에 사유 누적 (silent 차단).

        사용자/audit reviewer가 산출물 헤더 X-SwUT-Warnings에서 read 실패 인지 가능.
        """
        cfg_setup({"projects": {"HDPDM01": {}}})

        class _FakeResolver:
            def read_bytes(self, path):
                raise FileNotFoundError(f"HMR 파일 없음: {path}")

        import backend.services.file_resolver as fr_mod
        monkeypatch.setattr(fr_mod, "get_resolver", lambda: _FakeResolver())

        req = SimpleNamespace(hmr_html_path="U:/missing.html", project_id="HDPDM01")
        warnings: list[str] = []
        result = resolver.resolve_hmr_html_bytes(req, "HDPDM01", out_warnings=warnings)
        assert result is None
        assert len(warnings) == 1
        assert "[hmr] read 실패" in warnings[0]
        assert "FileNotFoundError" in warnings[0]


class TestResolveSwutsTestSpecsWarnings:
    """F6 Round 1 W1: resolve_swuts_test_specs out_warnings 누적."""

    def test_out_warnings_on_read_failure(self, monkeypatch, cfg_setup):
        cfg_setup({"projects": {"HDPDM01": {}}})

        class _FakeResolver:
            def read_bytes(self, path):
                raise PermissionError(f"권한 거부: {path}")

        import backend.services.file_resolver as fr_mod
        monkeypatch.setattr(fr_mod, "get_resolver", lambda: _FakeResolver())

        req = SimpleNamespace(swuts_docx_path="U:/x.xlsm", project_id="HDPDM01")
        warnings: list[str] = []
        result = resolver.resolve_swuts_test_specs(req, "HDPDM01", out_warnings=warnings)
        assert result is None
        assert len(warnings) == 1
        assert "[swuts] read 실패" in warnings[0]
        assert "PermissionError" in warnings[0]


class TestResolveSwutsTestSpecsOutBytes:
    """라운드 108 MINOR-5 — out_xlsm_bytes out-param (SwUTCR spec 2회 read 제거)."""

    def test_out_bytes_populated_even_when_parse_fails(self, monkeypatch, cfg_setup):
        """read 성공 시 parse 결과와 무관하게 bytes append — FI 추출기는
        별도 파서라 SwUTS parse 실패와 독립적으로 재사용 가능해야 한다."""
        cfg_setup({"projects": {"HDPDM01": {}}})
        payload = b"not a real xlsm"

        class _FakeResolver:
            def read_bytes(self, path):
                return payload

        import backend.services.file_resolver as fr_mod
        monkeypatch.setattr(fr_mod, "get_resolver", lambda: _FakeResolver())

        req = SimpleNamespace(swuts_docx_path="U:/x.xlsm", project_id="HDPDM01")
        box: list[bytes] = []
        result = resolver.resolve_swuts_test_specs(
            req, "HDPDM01", out_warnings=[], out_xlsm_bytes=box,
        )
        assert result is None  # parse 실패 (가짜 bytes)
        assert box == [payload]  # read는 성공 — bytes 재사용 가능

    def test_out_bytes_empty_on_read_failure(self, monkeypatch, cfg_setup):
        cfg_setup({"projects": {"HDPDM01": {}}})

        class _FakeResolver:
            def read_bytes(self, path):
                raise FileNotFoundError(path)

        import backend.services.file_resolver as fr_mod
        monkeypatch.setattr(fr_mod, "get_resolver", lambda: _FakeResolver())

        req = SimpleNamespace(swuts_docx_path="U:/x.xlsm", project_id="HDPDM01")
        box: list[bytes] = []
        result = resolver.resolve_swuts_test_specs(
            req, "HDPDM01", out_warnings=[], out_xlsm_bytes=box,
        )
        assert result is None
        assert box == []

    def test_out_bytes_empty_when_no_path(self, cfg_setup):
        cfg_setup({"projects": {"HDPDM01": {}}})
        req = SimpleNamespace(swuts_docx_path="", project_id="HDPDM01")
        box: list[bytes] = []
        assert resolver.resolve_swuts_test_specs(
            req, "HDPDM01", out_xlsm_bytes=box,
        ) is None
        assert box == []


class TestSwudsOSErrorRound3NC2:
    """F6 Round 3 NC2: resolve_swuds_function_ids/asil_map OSError catch 확대."""

    def test_swuds_function_ids_catches_oserror(self, monkeypatch, cfg_setup):
        """resolve_swuds_function_ids — OSError (예: ConnectionError) graceful."""
        cfg_setup({"projects": {"HDPDM01": {}}})

        class _FakeResolver:
            def read_bytes(self, path):
                raise ConnectionError(f"Cloudium worker 연결 실패: {path}")

        import backend.services.file_resolver as fr_mod
        monkeypatch.setattr(fr_mod, "get_resolver", lambda: _FakeResolver())

        req = SimpleNamespace(swuds_docx_path="U:/swuds.docx", project_id="HDPDM01")
        # 이전: ConnectionError → unhandled → 500. NC2 fix 후: graceful None.
        result = resolver.resolve_swuds_function_ids(req, "HDPDM01")
        assert result is None

    def test_swuds_function_asil_map_catches_oserror(self, monkeypatch, cfg_setup):
        """resolve_swuds_function_asil_map — OSError graceful (빈 dict)."""
        cfg_setup({"projects": {"HDPDM01": {}}})

        class _FakeResolver:
            def read_bytes(self, path):
                raise IsADirectoryError(f"디렉토리: {path}")

        import backend.services.file_resolver as fr_mod
        monkeypatch.setattr(fr_mod, "get_resolver", lambda: _FakeResolver())

        req = SimpleNamespace(swuds_docx_path="U:/dir", project_id="HDPDM01")
        # 이전: IsADirectoryError → unhandled → 500. NC2 fix 후: graceful 빈 dict.
        result = resolver.resolve_swuds_function_asil_map(req, "HDPDM01")
        assert result == {}


class TestResolveSwudsMapsOutWarnings:
    """2026-06-10 KJPDS02 PV 검증 fix — resolve_swuds_maps의 silent failure 차단.

    cloudium allowed_prefixes 미포함 SwUDS 경로의 PermissionError가 backend
    로그에만 남고 산출물 AuditLog에는 'SwUDS 0건'으로만 보이던 문제 —
    out_warnings kwarg (F6 Round 1 W1 패턴 대칭)로 사유 노출.
    """

    def test_out_warnings_on_permission_error(self, monkeypatch):
        from types import SimpleNamespace
        from backend.services import swut_meta_resolver as mod

        monkeypatch.setattr(
            mod, "resolve_swuds_path", lambda req, pid: "U:/blocked/swuds.docx",
        )

        def _raise(_path):
            raise PermissionError("Cloudium 모드: 허용되지 않은 경로 접근 차단됨")

        monkeypatch.setattr(mod, "_cached_parse_swuds", _raise)

        warnings: list[str] = []
        req = SimpleNamespace(swuds_docx_path="", project_id="KJPDS02")
        asil_map, name_map = mod.resolve_swuds_maps(
            req, "KJPDS02", out_warnings=warnings,
        )
        assert asil_map == {} and name_map == {}
        assert len(warnings) == 1
        assert "PermissionError" in warnings[0]
        assert "allowed_prefixes" in warnings[0]

    def test_out_warnings_default_none_backward_compat(self, monkeypatch):
        """out_warnings 미전달 (기존 호출자) — 예외 없이 빈 맵 반환 계약 유지."""
        from types import SimpleNamespace
        from backend.services import swut_meta_resolver as mod

        monkeypatch.setattr(
            mod, "resolve_swuds_path", lambda req, pid: "U:/blocked/swuds.docx",
        )

        def _raise(_path):
            raise FileNotFoundError("없음")

        monkeypatch.setattr(mod, "_cached_parse_swuds", _raise)
        req = SimpleNamespace(swuds_docx_path="", project_id="KJPDS02")
        assert mod.resolve_swuds_maps(req, "KJPDS02") == ({}, {})

    def test_out_warnings_on_parse_not_ok(self, monkeypatch):
        from types import SimpleNamespace
        from backend.services import swut_meta_resolver as mod

        monkeypatch.setattr(
            mod, "resolve_swuds_path", lambda req, pid: "U:/ok/swuds.docx",
        )
        monkeypatch.setattr(
            mod, "_cached_parse_swuds", lambda _p: SimpleNamespace(ok=False),
        )
        warnings: list[str] = []
        req = SimpleNamespace(swuds_docx_path="", project_id="KJPDS02")
        assert mod.resolve_swuds_maps(req, "KJPDS02", out_warnings=warnings) == ({}, {})
        assert warnings and "ok=False" in warnings[0]

    def test_apply_function_asil_map_propagates_swuds_failure(self, monkeypatch):
        """apply_function_asil_map 경유 시 session.parse_warnings에 사유 누적."""
        from types import SimpleNamespace
        from backend.services import swut_meta_resolver as mod

        monkeypatch.setattr(mod, "resolve_c_source_root", lambda req, pid: "")
        monkeypatch.setattr(
            mod, "resolve_swuds_path", lambda req, pid: "U:/blocked/swuds.docx",
        )

        def _raise(_path):
            raise PermissionError("차단")

        monkeypatch.setattr(mod, "_cached_parse_swuds", _raise)

        session = SimpleNamespace(environments=[], parse_warnings=[])
        req = SimpleNamespace(
            swuds_docx_path="", c_source_root="", project_id="KJPDS02",
        )
        mod.apply_function_asil_map(req, session, "KJPDS02")
        assert any("[swuds] ASIL read 실패" in w for w in session.parse_warnings)
