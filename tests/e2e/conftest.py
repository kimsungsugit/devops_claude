# tests/e2e/conftest.py
"""Playwright E2E test configuration."""

from __future__ import annotations

import os

import pytest

# ⚠ 기본값이 **5173 / 7000** 이었다 — 이 저장소의 실제 포트가 아니다
#   (frontend dev = 5174, backend = 9000 — CLAUDE.md §Architecture · scripts/start.bat).
#   playwright 가 없어 전부 skip 되는 바람에 아무도 못 봤다. 누가 playwright 를 깔면
#   엉뚱한 포트로 붙어 "연결 거부"로 죽고, 그건 코드 결함처럼 보인다.
BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:5174")
BACKEND_URL = os.environ.get("E2E_BACKEND_URL", "http://localhost:9000")


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def backend_url():
    return BACKEND_URL
