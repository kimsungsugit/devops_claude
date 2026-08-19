"""워커 접속 설정은 **한 곳에서** 해석된다 — 진입점마다 복제하지 않는다.

2026-08-19 실사고: 기본 포트 8765 를 무관한 앱이 점유해 워커가
`WinError 10013` 으로 죽었다. `.env` 로 포트를 옮겼더니 이번엔 **백엔드만** 새 포트를
봤다 — `backend/main.py` 의 `load_dotenv` 를 타는 쪽만 반영됐고, uvicorn 을 안 거치는
**독립 스크립트는 전부 기본값 8765** 를 봐서 "Cloudium worker 미응답" 으로 죽었다.

진입점마다 `load_dotenv` 를 복제하는 건 같은 결함을 진입점 수만큼 만드는 것이다.
그래서 폴백을 **포트가 무엇인지 정의하는 모듈**(`file_resolver`)에 뒀다.

계약(이 파일이 고정한다):
  1. `os.environ` 이 이긴다 — 명시 설정 우선
  2. 없으면 저장소 `.env` 를 본다 — 부트스트랩을 안 거친 스크립트도 같은 값을 본다
  3. 둘 다 없으면 기본값
  4. **`os.environ` 을 오염시키지 않는다** — 다른 모듈 동작을 몰래 바꾸지 않기 위해
  5. 숫자가 아니면 조용히 기본값으로 가지 않고 **경고를 남긴다**
"""

from __future__ import annotations

import logging

import pytest

from backend.services import file_resolver as fr


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """환경변수·파일 캐시를 매 테스트 격리. 전역을 특정 값으로 고정하지 않고 복원한다."""
    monkeypatch.delenv("CLOUDIUM_WORKER_PORT", raising=False)
    monkeypatch.delenv("CLOUDIUM_WORKER_HOST", raising=False)
    saved = fr._env_file_cache
    fr._env_file_cache = (False, {})
    yield
    fr._env_file_cache = saved


def _stub_env_file(monkeypatch, mapping: dict):
    monkeypatch.setattr(fr, "_env_file_cache", (True, dict(mapping)), raising=False)


class TestPrecedence:
    def test_environ_wins_over_env_file(self, monkeypatch):
        _stub_env_file(monkeypatch, {"CLOUDIUM_WORKER_PORT": "8766"})
        monkeypatch.setenv("CLOUDIUM_WORKER_PORT", "9101")
        assert fr._worker_endpoint()[1] == 9101

    def test_env_file_used_when_environ_absent(self, monkeypatch):
        """이게 이 파일의 핵심 — 부트스트랩을 안 거친 스크립트가 보는 경로다."""
        _stub_env_file(monkeypatch, {"CLOUDIUM_WORKER_PORT": "8766"})
        assert fr._worker_endpoint()[1] == 8766

    def test_default_when_neither(self, monkeypatch):
        _stub_env_file(monkeypatch, {})
        assert fr._worker_endpoint()[1] == fr.DEFAULT_WORKER_PORT

    def test_host_follows_the_same_rule(self, monkeypatch):
        """포트만 고치고 host 를 두면 같은 비대칭이 host 축에서 재발한다."""
        _stub_env_file(monkeypatch, {"CLOUDIUM_WORKER_HOST": "10.0.0.9"})
        assert fr._worker_endpoint()[0] == "10.0.0.9"
        monkeypatch.setenv("CLOUDIUM_WORKER_HOST", "127.0.0.5")
        assert fr._worker_endpoint()[0] == "127.0.0.5"


class TestNoEnvironPollution:
    """⚠ 첫 판은 **뮤테이션이 살아남았다**. `_env_file_cache` 를 미리 채워 두면
    `_env_file_values()` 가 캐시에서 즉시 반환해 **주입이 일어나는 코드 경로를 아예
    안 탄다** — 오염을 심어도 테스트가 통과했다. 실제 파일 읽기를 강제해야 한다.
    (같은 함정: 세션 메모리 `가드는 관측량을 단언할 것`)
    """

    def test_env_file_values_do_not_leak_into_environ(self, monkeypatch, tmp_path):
        import os

        env = tmp_path / ".env"
        env.write_text("CLOUDIUM_WORKER_PORT=8771\n", encoding="utf-8")
        monkeypatch.setattr(fr, "_PROJECT_ROOT", tmp_path)
        fr._env_file_cache = (False, {})          # 캐시 미스 → 실제로 파일을 읽는다

        assert fr._worker_endpoint()[1] == 8771, "폴백 자체가 안 돌면 이 테스트는 공허하다"
        assert os.getenv("CLOUDIUM_WORKER_PORT") is None, (
            ".env 값이 os.environ 에 주입됐다 — 다른 모듈 동작이 몰래 바뀐다"
        )

    def test_other_keys_also_stay_out_of_environ(self, monkeypatch, tmp_path):
        """포트만 막고 host 를 흘리면 같은 결함이 다른 키에서 남는다."""
        import os

        (tmp_path / ".env").write_text(
            "CLOUDIUM_WORKER_HOST=127.0.0.9\nCLOUDIUM_GATE_PROCESS=x.exe\n",
            encoding="utf-8")
        monkeypatch.setattr(fr, "_PROJECT_ROOT", tmp_path)
        fr._env_file_cache = (False, {})
        assert fr._worker_endpoint()[0] == "127.0.0.9"
        assert os.getenv("CLOUDIUM_WORKER_HOST") is None
        assert os.getenv("CLOUDIUM_GATE_PROCESS") is None


class TestBadValueIsReported:
    def test_non_numeric_falls_back_but_warns(self, monkeypatch, caplog):
        """조용히 기본값으로 가면 '포트를 바꿨는데 왜 안 되지' 로 진단이 헛돈다."""
        _stub_env_file(monkeypatch, {})
        monkeypatch.setenv("CLOUDIUM_WORKER_PORT", "not-a-port")
        with caplog.at_level(logging.WARNING, logger="devops_api.file_resolver"):
            assert fr._worker_endpoint()[1] == fr.DEFAULT_WORKER_PORT
        assert any("CLOUDIUM_WORKER_PORT" in r.message for r in caplog.records), (
            "숫자가 아닌 값이 무시됐는데 아무 말도 안 했다"
        )


class TestEnvFileParsing:
    """`.env` 파싱은 dotenv 없이 직접 한다 — 형식 처리를 고정한다."""

    def test_parses_quotes_comments_and_blank_lines(self, monkeypatch, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "\n".join([
                "# comment",
                "",
                'CLOUDIUM_WORKER_PORT="8770"',
                "CLOUDIUM_WORKER_HOST = '127.0.0.2' ",
                "OTHER_KEY=ignored",
                "malformed-line-without-equals",
            ]),
            encoding="utf-8",
        )
        monkeypatch.setattr(fr, "_PROJECT_ROOT", tmp_path)
        fr._env_file_cache = (False, {})
        vals = fr._env_file_values()
        assert vals["CLOUDIUM_WORKER_PORT"] == "8770"
        assert vals["CLOUDIUM_WORKER_HOST"] == "127.0.0.2"
        # CLOUDIUM_ 접두 외에는 담지 않는다 — 이 폴백의 범위를 좁게 유지한다
        assert "OTHER_KEY" not in vals

    def test_missing_env_file_is_not_an_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fr, "_PROJECT_ROOT", tmp_path / "nope")
        fr._env_file_cache = (False, {})
        assert fr._env_file_values() == {}
        assert fr._worker_endpoint()[1] == fr.DEFAULT_WORKER_PORT
