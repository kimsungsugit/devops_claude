"""백엔드 성능 캐시 회귀 테스트.

- 캐시 C: workflow.ai.load_oai_configs mtime 캐시 (hit / 무효화 / mutation 격리)
- 캐시 D: backend.mcp.report_server.ReportMCPServer.read_bundle mtime-only hit (TTL 버그 fix)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402  (sys.path 부트스트랩 뒤라 순서가 의도됨)

import workflow.ai as ai  # noqa: E402  (sys.path 부트스트랩 뒤라 순서가 의도됨)


@pytest.fixture(autouse=True)
def _clear_caches():
    ai._oai_configs_cache.clear()
    yield
    ai._oai_configs_cache.clear()


def test_load_oai_configs_caches_by_mtime(tmp_path, monkeypatch):
    cfg = tmp_path / "oai.json"
    cfg.write_text('[{"model": "m1", "api_type": "google", "api_key": "k"}]', encoding="utf-8")

    import pathlib
    real_read = pathlib.Path.read_text
    reads = []

    def _counting(self, *a, **k):
        if str(self) == str(cfg):
            reads.append(1)
        return real_read(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", _counting)

    r1 = ai.load_oai_configs(str(cfg))
    r2 = ai.load_oai_configs(str(cfg))
    assert len(reads) == 1  # 두 번째 호출은 mtime 캐시 hit → 재read 없음
    assert r1 == r2
    assert any(it.get("model") == "m1" for it in r1)

    # 반환값 mutation 이 캐시 원본을 오염시키지 않아야 함
    r1.append({"poison": True})
    r3 = ai.load_oai_configs(str(cfg))
    assert all("poison" not in it for it in r3)
    assert len(reads) == 1  # 여전히 캐시 hit

    # mtime 변경 → 재파싱(miss)
    cfg.write_text('[{"model": "m2", "api_type": "google", "api_key": "k"}]', encoding="utf-8")
    st = os.stat(cfg)
    bump = st.st_mtime_ns + 5_000_000_000
    os.utime(cfg, ns=(bump, bump))
    r4 = ai.load_oai_configs(str(cfg))
    assert len(reads) == 2  # mtime 달라져 재파싱
    assert any(it.get("model") == "m2" for it in r4)


def test_read_bundle_cache_hit_regardless_of_age(tmp_path, monkeypatch):
    import backend.mcp.report_server as rs

    rd = tmp_path / "rep"
    rd.mkdir()
    (rd / "analysis_summary.json").write_text('{"coverage": {"line_rate": 0.9}}', encoding="utf-8")
    (rd / "run_status.json").write_text('{"status": "ok"}', encoding="utf-8")

    # 산출물을 1시간 전으로 (구버그면 TTL 60s 초과로 영원히 miss)
    old = os.stat(rd / "analysis_summary.json").st_mtime_ns - 3600 * 1_000_000_000
    os.utime(rd / "analysis_summary.json", ns=(old, old))
    os.utime(rd / "run_status.json", ns=(old, old))

    reads = []
    real = rs._read_json
    monkeypatch.setattr(rs, "_read_json", lambda *a, **k: (reads.append(1), real(*a, **k))[1])

    srv = rs.ReportMCPServer()
    b1 = srv.read_bundle(rd)
    n_first = len(reads)
    b2 = srv.read_bundle(rd)
    assert b1 == b2
    assert len(reads) == n_first  # 두 번째는 캐시 hit — 오래된 mtime 이어도 재read 없음
    assert n_first >= 1
