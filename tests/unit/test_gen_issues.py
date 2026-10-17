"""(R48-b) 생성 중 문제 수집기 `report_gen/gen_issues.py`.

- contextvar 로 전달된다: `use_collector()` 안의 `note_issue()` 만 쌓이고, 밖에서는 아무 일도 없다(관측의 부재가 판정을 바꾸지 않는다).
- 같은 `(code, message)` 는 한 번만. 상한을 넘으면 `issues_truncated` 한 건으로 **넘쳤다는 사실**을 남긴다.
- 어휘(`severity`/`kind`) 밖 값은 예외 — 화면 배지가 모르는 값으로 조용히 회색이 되지 않게.
- `issue_payload(None)` 은 빈 목록이 아니라 `issues_recorded: False` 다.
"""
from __future__ import annotations

import threading

import pytest

from report_gen import gen_issues as gi


class TestCollector:
    def test_add_dedupes_and_counts(self):
        c = gi.IssueCollector()
        assert c.add("a", "error", "actual", "x  y\n z") is not None
        assert c.add("a", "error", "actual", "x y z") is None          # 공백 정규화 후 같은 메시지
        assert c.add("a", "warning", "potential", "다른 메시지") is not None
        assert len(c) == 2
        items = c.as_list()
        assert items[0]["message"] == "x y z" and items[0]["at"]
        assert c.counts() == {"total": 2, "actual": 1, "potential": 1, "by_severity": {"error": 1, "warning": 1, "risk": 0}}

    @pytest.mark.parametrize("sev,kind", [("fatal", "actual"), ("error", "maybe"), ("", "actual")])
    def test_vocabulary_is_enforced(self, sev, kind):
        c = gi.IssueCollector()
        with pytest.raises(ValueError):
            c.add("a", sev, kind, "m")
        with pytest.raises(ValueError):
            c.add("", "error", "actual", "m")

    def test_overflow_is_disclosed_not_silent(self):
        c = gi.IssueCollector()
        for i in range(gi.MAX_ISSUES + 7):
            c.add("many", "warning", "actual", f"m{i}")
        items = c.as_list()
        assert len(items) == gi.MAX_ISSUES + 1
        last = items[-1]
        assert last["code"] == "issues_truncated" and last["facts"] == {"dropped": 7, "max": gi.MAX_ISSUES}
        assert c.counts()["total"] == gi.MAX_ISSUES + 1

    def test_message_is_capped(self):
        c = gi.IssueCollector()
        c.add("a", "risk", "potential", "x" * 1000)
        assert len(c.as_list()[0]["message"]) == gi.MESSAGE_MAX

    def test_thread_safe_adds(self):
        c = gi.IssueCollector()

        def work(n):
            for i in range(50):
                c.add(f"t{n}", "warning", "actual", f"m{i}")
        ts = [threading.Thread(target=work, args=(n,)) for n in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert len(c) == gi.MAX_ISSUES   # 200 = 4*50 정확히 상한
        assert c.counts()["total"] == gi.MAX_ISSUES


class TestContextVar:
    def test_note_issue_outside_context_is_noop(self):
        assert gi.current_collector() is None
        assert gi.note_issue("a", "error", "actual", "m") is None

    def test_note_issue_inside_context_collects_and_restores(self):
        with gi.use_collector() as c:
            assert gi.current_collector() is c
            assert gi.note_issue("a", "error", "actual", "m", stage="docx", facts={"n": 1}) is not None
            with gi.use_collector() as inner:       # 중첩 — 안쪽이 이기고 나오면 복원
                gi.note_issue("b", "risk", "potential", "inner")
                assert gi.current_collector() is inner
            assert gi.current_collector() is c
        assert gi.current_collector() is None
        assert [i["code"] for i in c.as_list()] == ["a"]
        assert c.as_list()[0]["stage"] == "docx" and c.as_list()[0]["facts"] == {"n": 1}
        assert [i["code"] for i in inner.as_list()] == ["b"]

    def test_context_is_per_thread_unless_copied(self):
        """다른 스레드는 수집기를 보지 못한다 — 파이프라인이 자기 스레드 안에서 여는 이유."""
        seen = {}
        with gi.use_collector():
            t = threading.Thread(target=lambda: seen.update(c=gi.current_collector()))
            t.start()
            t.join()
        assert seen["c"] is None

    def test_issue_payload_distinguishes_absence(self):
        assert gi.issue_payload(None) == {"issues": [], "issue_counts": None, "issues_recorded": False}
        c = gi.IssueCollector()
        p = gi.issue_payload(c)
        assert p["issues_recorded"] is True and p["issues"] == [] and p["issue_counts"]["total"] == 0
