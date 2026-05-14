"""38차 W1 — swut_builder_helpers 회귀.

DRY 추출 helper extract_warnings_from_session의 3 시나리오:
  1. 정상: parse_warnings에 3건 → 동일 list 반환
  2. None: parse_warnings=None → 빈 list
  3. empty: parse_warnings=[] → 빈 list
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.swut_builder_helpers import extract_warnings_from_session  # noqa: E402
from backend.services.swut_input_adapter import SwUTSession  # noqa: E402


class TestExtractWarningsFromSession:
    """38차 W1: 빌더 4개의 DRY 위반을 단일 helper로 추출."""

    def test_normal_parse_warnings_returned_as_copy(self):
        """정상 — parse_warnings 3건 → 동일 list 반환 (shallow copy)."""
        session = SwUTSession(parse_warnings=["w1", "w2", "w3"])
        result = extract_warnings_from_session(session)
        assert result == ["w1", "w2", "w3"]
        # shallow copy 확인 — 원본 변경이 result에 영향 없음
        session.parse_warnings.append("w4")
        assert "w4" not in result, "shallow copy 보장 — 원본 변경이 result에 누설되지 않아야 함"

    def test_none_parse_warnings_returns_empty_list(self):
        """parse_warnings=None → 빈 list (37차 graceful 패턴)."""
        # SwUTSession의 parse_warnings는 field(default_factory=list)이라 None 직접 할당
        session = SwUTSession()
        session.parse_warnings = None  # type: ignore[assignment]
        result = extract_warnings_from_session(session)
        assert result == []

    def test_empty_parse_warnings_returns_empty_list(self):
        """parse_warnings=[] → 빈 list."""
        session = SwUTSession(parse_warnings=[])
        result = extract_warnings_from_session(session)
        assert result == []
