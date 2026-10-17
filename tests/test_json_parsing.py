"""`workflow.uds_ai._extract_json_payload` — LLM 응답에서 JSON 을 건져내는 규약.

⚠ 이 파일은 원래 **pytest 테스트가 아니라 스크립트**였다(2026-08-21 발견). `test_*` 함수도
  `Test*` 클래스도 없이 import 시점에 루프를 돌며 `print("PASS"/"FAIL")` 만 찍었다.
  `pyproject.toml` 의 `python_files = ["test_*.py"]` 때문에 pytest 가 수집하려고 **import
  는 하므로 검사는 실행되지만**, 단언이 없어 **절대 실패할 수 없었다** — 파일 이름은
  `test_` 인데 게이트에는 `collected 0 items` 로 보인다(rc=5 "no tests ran").
  전형적인 fake-green 이라 진짜 테스트로 승격했다. 기대값은 그대로다(승격 직전 실측 7/7 통과).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from workflow.uds_ai import _extract_json_payload  # noqa: E402  (sys.path 조정 뒤라 여기여야 한다)

# (입력, JSON 을 건져낼 수 있어야 하는가)
CASES = [
    ('{"a":1}', True),                              # 순수 JSON
    ('```json\n{"a":1}\n```', True),                # 코드펜스로 감싼 응답
    ('{"a":1,}', True),                             # 후행 쉼표 — 모델이 자주 낸다
    ('{"a":"hello"', True),                         # 닫는 괄호 누락(토큰 절단)
    ('Sure! Here is JSON:\n{"a":1}', True),         # 서두 붙은 응답
    ("", False),                                    # 빈 응답
    ("not json", False),                            # JSON 이 아예 없음
]


@pytest.mark.parametrize(("raw", "expect_payload"), CASES, ids=[repr(c[0])[:32] for c in CASES])
def test_extract_json_payload(raw, expect_payload):
    got = _extract_json_payload(raw) is not None
    assert got is expect_payload, (
        f"입력 {raw!r} 에서 payload 를 "
        f"{'못 건졌다' if expect_payload else '건져냈다'} — "
        "모델 응답 파싱 규약이 바뀌었다면 위 CASES 도 함께 갱신할 것"
    )
