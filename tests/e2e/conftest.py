# tests/e2e/conftest.py
"""Playwright E2E test configuration."""

from __future__ import annotations

import os
import pytest

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:5173")
BACKEND_URL = os.environ.get("E2E_BACKEND_URL", "http://localhost:7000")


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def backend_url():
    return BACKEND_URL
