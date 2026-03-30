from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


_TMP_ROOT = Path(__file__).resolve().parents[1] / ".codex_tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def tmp_path() -> Path:
    path = _TMP_ROOT / f"pytest-{uuid.uuid4().hex[:12]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
