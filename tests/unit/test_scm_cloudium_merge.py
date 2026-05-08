"""Tests for N9 fix (C): SCM register/update가 cloudium 모드에서
source_root + linked_docs 부모를 allowed_prefixes에 자동 merge하는지 검증."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.routers import scm as scm_router
from backend.services import file_resolver
from backend.services.file_resolver import CloudiumFileResolver, LocalFileResolver


@pytest.fixture(autouse=True)
def _reset_resolver():
    file_resolver.invalidate_gate_cache()
    file_resolver.set_resolver(LocalFileResolver())
    yield
    file_resolver.invalidate_gate_cache()
    file_resolver.set_resolver(LocalFileResolver())


def _make_entry(source_root="", linked_docs=None):
    """간이 entry 객체 — model_dump를 가진 mock으로 충분."""
    class _Linked:
        def __init__(self, d):
            self._d = d or {}

        def model_dump(self):
            return self._d

    class _Entry:
        pass

    e = _Entry()
    e.source_root = source_root
    e.linked_docs = _Linked(linked_docs or {})
    return e


def test_merge_no_op_in_local_mode():
    """local 모드에서는 아무 동작도 하지 않아야."""
    file_resolver.set_resolver(LocalFileResolver())
    entry = _make_entry(source_root="U:/cloudium/proj")
    with patch("backend.services.file_resolver.switch_mode") as mock_switch:
        scm_router._merge_paths_to_cloudium_prefixes(entry)
    mock_switch.assert_not_called()


def test_merge_adds_source_root_parent_in_cloudium_mode():
    """cloudium 모드에서 source_root의 부모 디렉토리가 allowed_prefixes에 추가."""
    cloudium = CloudiumFileResolver(allowed_prefixes="")
    file_resolver.set_resolver(cloudium)
    entry = _make_entry(source_root="U:/cloudium/proj/src")
    with patch("backend.services.file_resolver.switch_mode") as mock_switch:
        scm_router._merge_paths_to_cloudium_prefixes(entry)
    mock_switch.assert_called_once()
    args, kwargs = mock_switch.call_args
    assert args[0] == "cloudium"
    # 부모 디렉토리("U:/cloudium/proj")가 prefix에 포함
    assert "U:/cloudium/proj" in kwargs["allowed_prefixes"].replace("\\", "/")


def test_merge_handles_multi_path_source_root():
    """source_root가 콤마/세미콜론 구분 multi-path여도 각 부모를 추가."""
    cloudium = CloudiumFileResolver(allowed_prefixes="")
    file_resolver.set_resolver(cloudium)
    entry = _make_entry(source_root="U:/a/src1, U:/b/src2; U:/c/src3")
    with patch("backend.services.file_resolver.switch_mode") as mock_switch:
        scm_router._merge_paths_to_cloudium_prefixes(entry)
    args, kwargs = mock_switch.call_args
    merged = kwargs["allowed_prefixes"].replace("\\", "/")
    assert "U:/a" in merged
    assert "U:/b" in merged
    assert "U:/c" in merged


def test_merge_adds_linked_docs_parents():
    """linked_docs 각 doc type의 부모 디렉토리도 추가."""
    cloudium = CloudiumFileResolver(allowed_prefixes="")
    file_resolver.set_resolver(cloudium)
    entry = _make_entry(
        source_root="",
        linked_docs={"srs": "U:/docs/srs.docx", "uds": "U:/docs/uds.xlsx", "hsis": ""},
    )
    with patch("backend.services.file_resolver.switch_mode") as mock_switch:
        scm_router._merge_paths_to_cloudium_prefixes(entry)
    args, kwargs = mock_switch.call_args
    merged = kwargs["allowed_prefixes"].replace("\\", "/")
    assert "U:/docs" in merged


def test_merge_skips_already_existing_prefix():
    """이미 prefix에 있는 경로는 중복 추가 안 함."""
    cloudium = CloudiumFileResolver(allowed_prefixes="U:/cloudium")
    file_resolver.set_resolver(cloudium)
    # source_root의 부모(U:/cloudium/proj)는 U:/cloudium 하위 → skip
    entry = _make_entry(source_root="U:/cloudium/proj/src")
    with patch("backend.services.file_resolver.switch_mode") as mock_switch:
        scm_router._merge_paths_to_cloudium_prefixes(entry)
    mock_switch.assert_not_called()  # 새 추가 없음 → switch_mode 호출 안 됨


def test_merge_no_op_when_entry_paths_all_empty():
    """source_root + linked_docs 모두 비어있으면 no-op."""
    cloudium = CloudiumFileResolver(allowed_prefixes="")
    file_resolver.set_resolver(cloudium)
    entry = _make_entry(source_root="", linked_docs={"srs": "", "uds": ""})
    with patch("backend.services.file_resolver.switch_mode") as mock_switch:
        scm_router._merge_paths_to_cloudium_prefixes(entry)
    mock_switch.assert_not_called()
