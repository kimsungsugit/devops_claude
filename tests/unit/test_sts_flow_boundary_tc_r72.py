"""R72 (N81) — logic_flow 가 있는 함수에도 경계값 TC 가 선다(분기 TC 뒤에 하나, 밀어내기 없음).

실측(KJPDS02, 2026-09-19): flow 함수 973개 중 경계값을 만들 수 있는 입력을 가진 330개의 BAA 가 0 — 경계값은
`_generate_simple_steps`(flow 없는 함수) 전용이었다. 상한(함수당 `max_tc` · 요구당 `max_tc_per_req`)은 그대로이고 경계값 TC 는
마지막 자리라 가장 먼저 잘린다 — 잘린 수를 통계와 경고로 남겨 상한 결정(T 축)은 사람이 한다.
"""
from __future__ import annotations

from generators.sts import (
    _classify_steps,
    _generate_steps_from_flow,
    generate_quality_report,
    generate_test_cases,
    generate_traceability_matrix,
)

_IF = [{"type": "if", "condition": "n > 10", "true_body": [{"type": "call", "name": "A"}],
        "false_body": [{"type": "call", "name": "B"}]}]


def _fn(name="Fn", inputs=("[IN] U8 n",), flow=None):
    return {"id": name, "name": name, "prototype": f"void {name}(U8 n)", "inputs": list(inputs), "outputs": [],
            "calls_list": [], "logic_flow": _IF if flow is None else flow}


def _is_boundary(tc):
    return _classify_steps(tc)[1] == "BAA"


class TestStepsFromFlow:
    def test_boundary_tc_is_appended_after_branch_tcs(self):
        stats: dict = {}
        tcs = _generate_steps_from_flow(_IF, _fn(), max_steps=15, max_tc=5, stats=stats)
        assert len(tcs) == 3, [t[0]["action"] for t in tcs]
        assert not _is_boundary(tcs[0]) and not _is_boundary(tcs[1]), "분기 TC 는 그대로 앞에 선다"
        assert _is_boundary(tcs[2]) and any("n=0" in s["action"] for s in tcs[2]) and any("n=255" in s["action"] for s in tcs[2])
        assert stats["boundary_tc_candidates"] == 1 and "boundary_tc_cut_by_function_cap" not in stats

    def test_branch_tcs_are_byte_identical_to_before(self):
        """덧붙이기만 한다 — 분기 TC 의 내용·순서는 입력 유무와 무관하게 같다."""
        with_b = _generate_steps_from_flow(_IF, _fn(), max_steps=15, max_tc=5)
        without = _generate_steps_from_flow(_IF, _fn(inputs=()), max_steps=15, max_tc=5)
        assert with_b[:2] == without and len(without) == 2

    def test_no_boundary_when_no_input_has_a_known_type(self):
        """R71 규칙 그대로 — `void *`·모르는 typedef 뿐이면 경계값이 없으니 경계 TC 도 없다(지어내지 않는다). 못 붙인 사실은 센다."""
        stats: dict = {}
        tcs = _generate_steps_from_flow(_IF, _fn(inputs=("[IN] void *p", "[IN] EEPROM_TAddress a")), max_steps=15, max_tc=5,
                                        stats=stats)
        assert len(tcs) == 2 and not any(_is_boundary(t) for t in tcs)
        assert "boundary_tc_candidates" not in stats and stats["boundary_tc_unavailable"] == 1
        assert stats["boundary_appended"] is False

    def test_undeclared_input_uses_name_rule_only_never_the_uint8_default(self):
        """(리뷰 W1) 선언 없는 입력 — 이름 규칙(`u8_`)이 말하면 경계값, 아무 규칙도 없으면 경계값 없음(기본 uint8 금지)."""
        tcs = _generate_steps_from_flow(_IF, _fn(inputs=("SomeThing",)), max_steps=15, max_tc=5)
        assert len(tcs) == 2 and not any(_is_boundary(t) for t in tcs)
        tcs2 = _generate_steps_from_flow(_IF, _fn(inputs=("u8_Level",)), max_steps=15, max_tc=5)
        assert _is_boundary(tcs2[-1]) and any("u8_Level=255" in s["action"] for s in tcs2[-1])

    def test_flowless_function_is_unchanged_and_not_counted(self):
        stats: dict = {}
        tcs = _generate_steps_from_flow([], _fn(flow=[]), max_steps=15, max_tc=5, stats=stats)
        assert len(tcs) == 3 and _is_boundary(tcs[1]), "flow 없는 함수의 TC1/TC2/TC3 는 종전 그대로"
        # (R76 N93) `boundary_index` 는 계수가 아니라 **자리 안내**다 — flow 없는 함수의 경계값 TC 는 둘째 자리(영향도 초안이
        #   미리보기에서 그 TC 를 남길 때 쓴다). 계수 키(`boundary_tc_candidates` 등)는 여전히 하나도 생기지 않는다.
        assert stats == {"boundary_appended": False, "boundary_index": 1}

    def test_flow_that_yields_no_branch_falls_back_to_simple_steps_without_a_duplicate(self):
        """logic_flow 는 있는데 아는 노드가 없어 분기 TC 가 0 인 함수 — 종전대로 단순 스텝 3개(경계 TC 는 그 안의 하나)이지
        경계 TC 를 한 번 더 붙이지 않는다(뮤테이션 M4)."""
        stats: dict = {}
        tcs = _generate_steps_from_flow([{"type": "comment", "text": "n/a"}], _fn(), max_steps=15, max_tc=5, stats=stats)
        # 단순 스텝은 TC2(경계 최솟/최댓값)·TC3(유효 범위 초과) 둘이 BAA 다 — 셋이면 그대로, 넷이면 중복이다.
        assert len(tcs) == 3 and sum(1 for t in tcs if _is_boundary(t)) == 2
        assert "boundary_tc_candidates" not in stats and stats["boundary_appended"] is False

    def test_function_cap_cuts_the_boundary_tc_first_and_counts_it(self):
        """상한이 꽉 차면 경계값 TC 가 먼저 잘린다(분기 TC 를 밀어내지 않는다) — 잘린 사실은 센다."""
        stats: dict = {}
        tcs = _generate_steps_from_flow(_IF, _fn(), max_steps=15, max_tc=2, stats=stats)
        assert len(tcs) == 2 and not any(_is_boundary(t) for t in tcs)
        assert stats["boundary_tc_candidates"] == 1 and stats["boundary_tc_cut_by_function_cap"] == 1
        assert stats["boundary_appended"] is False

    def test_too_small_max_steps_means_no_boundary_tc(self):
        """(리뷰 W3) 경계 TC 는 최솟값·호출·최댓값·호출 4스텝이 최소다 — `max_steps<4` 면 한 축이 잘린 채 BAA 만 남으니 붙이지 않는다."""
        stats: dict = {}
        tcs = _generate_steps_from_flow(_IF, _fn(), max_steps=3, max_tc=5, stats=stats)
        assert len(tcs) == 2 and all(len(t) <= 3 for t in tcs) and stats["boundary_tc_unavailable"] == 1
        tcs4 = _generate_steps_from_flow(_IF, _fn(), max_steps=4, max_tc=5)
        assert _is_boundary(tcs4[-1]) and len(tcs4[-1]) == 4

    def test_appended_flag_is_reset_per_call(self):
        """호출별 위치 판정 — 이전 호출의 True 가 다음 호출로 새면 분기 TC 가 경계 TC 로 계수된다(리뷰 C1 의 다른 얼굴)."""
        stats: dict = {}
        _generate_steps_from_flow(_IF, _fn(), max_steps=15, max_tc=5, stats=stats)
        assert stats["boundary_appended"] is True
        _generate_steps_from_flow(_IF, _fn(inputs=()), max_steps=15, max_tc=5, stats=stats)
        assert stats["boundary_appended"] is False


class TestRequirementCap:
    @staticmethod
    def _run(max_tc, n_fns=2):
        fd = {f"SwUFn_{i:03d}": _fn(f"S_Fn_{i}") for i in range(1, n_fns + 1)}
        stats: dict = {}
        tcs = generate_test_cases([{"id": "SwTR_0001", "req_type": "TR"}], fd, {"SwTR_0001": list(fd)},
                                  {"max_tc_per_req": max_tc}, stats_out=stats)
        return tcs, stats

    def test_requirement_cap_cut_is_counted_separately(self):
        """f1: 분기 2 + 경계 1 = 3 → f2: 분기 2 중 1개로 상한 4 도달 → f2 의 분기 1 + 경계 1 이 잘린다(경계 1 로 계수)."""
        tcs, stats = self._run(max_tc=4)
        assert len(tcs) == 4
        assert stats["boundary_tc_candidates"] == 2 and stats["boundary_tc_kept"] == 1
        assert stats["boundary_tc_cut_by_req_cap"] == 1 and stats["boundary_tc_cut_by_function_cap"] == 0
        assert sum(1 for t in tcs if t["gen_method"] == "BAA") == 1

    def test_no_cut_when_under_cap(self):
        tcs, stats = self._run(max_tc=10)
        assert len(tcs) == 6 and stats["boundary_tc_kept"] == 2 and stats["boundary_tc_cut_by_req_cap"] == 0
        assert [t["gen_method"] for t in tcs] == ["ECA", "ECA", "BAA", "ECA", "ECA", "BAA"]

    def test_stats_out_is_json_serializable(self):
        import json

        _, stats = self._run(max_tc=4)
        json.dumps(stats)
        assert "boundary_ids" not in stats and "boundary_appended" not in stats

    def test_invariant_holds_at_scale_and_kept_equals_document_baa(self):
        """(리뷰 C1·I5) 수백 함수에서 `candidates == kept + cut_fn + cut_req` 이고 `kept` 가 문서의 BAA TC 수와 같아야 한다.
        옛 `id(tc)` 집합은 해제된 리스트의 주소 재사용으로 분기 TC 를 경계 TC 로 오계수했다(실측 kept+cut > candidates)."""
        fns = {}
        for i in range(1, 301):
            kind = i % 3
            inputs = ("[IN] U8 n",) if kind != 2 else ("[IN] void *p",)
            flow = _IF if kind != 1 else [{"type": "if", "condition": "n > 1", "true_body": [], "false_body": []},
                                          {"type": "if", "condition": "n > 2", "true_body": [], "false_body": []},
                                          {"type": "if", "condition": "n > 3", "true_body": [], "false_body": []}]
            fns[f"SwUFn_{i:04d}"] = _fn(f"S_Fn_{i}", inputs=inputs, flow=flow)
        reqs = [{"id": f"SwTR_{r:04d}", "req_type": "TR"} for r in range(1, 41)]
        ids = list(fns)
        mapping = {r["id"]: ids[(j * 7) % 300:(j * 7) % 300 + 12] for j, r in enumerate(reqs)}
        for max_tc in (3, 5, 9, 400):
            stats: dict = {}
            tcs = generate_test_cases(reqs, fns, mapping, {"max_tc_per_req": max_tc}, stats_out=stats)
            c, k, f, r = (stats[x] for x in ("boundary_tc_candidates", "boundary_tc_kept",
                                              "boundary_tc_cut_by_function_cap", "boundary_tc_cut_by_req_cap"))
            assert c == k + f + r, (max_tc, c, k, f, r)
            assert k == sum(1 for t in tcs if t["gen_method"] == "BAA"), (max_tc, k)
            assert stats["boundary_tc_unavailable"] > 0


class TestQualityReportWarning:
    def _qr(self, max_tc):
        fd = {f"SwUFn_{i:03d}": _fn(f"S_Fn_{i}") for i in range(1, 3)}
        reqs = [{"id": "SwTR_0001", "req_type": "TR"}]
        stats: dict = {}
        tcs = generate_test_cases(reqs, fd, {"SwTR_0001": list(fd)}, {"max_tc_per_req": max_tc}, stats_out=stats)
        return generate_quality_report(tcs, generate_traceability_matrix(tcs, reqs), generation_stats=stats)

    def test_cut_boundary_tcs_are_named_in_coverage_warnings(self):
        qr = self._qr(max_tc=4)
        hit = [w for w in qr["coverage_warnings"] if "경계값 TC" in w]
        assert len(hit) == 1 and "2건 중 1건" in hit[0] and "요구당 1" in hit[0] and "밀어내지 않는다" in hit[0], qr["coverage_warnings"]

    def test_quiet_when_nothing_is_cut(self):
        qr = self._qr(max_tc=10)
        assert not [w for w in qr["coverage_warnings"] if "경계값 TC" in w]
        assert qr["generation_stats"]["boundary_tc_kept"] == 2
