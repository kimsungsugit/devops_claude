"""정본 SwUDS 블록 → payload 함수 매칭은 **이름**이다 (R51 N40).

왜 이 파일이 있나 — 실측(2026-09-15, kjpds02_pv 정본 v3.03 × run 2080): 옛 규칙 "ID 먼저, 없으면 이름" 으로 ID 가 맞은
819 블록 중 **773 이 이름이 다른 함수**였다(정본 SwUFn_0101 = main, 생성본 SwUFn_0101 = ADC_MONITOR_Enable). 생성 ID 는
소스 스캔 순서로 붙는 번호라 정본 번호와 무관한데, 그 엉뚱한 블록의 ASIL 763 · Related 762 · precondition 729 ·
inputs 368 · outputs 372 · called 339 건이 다른 함수에 실려 있었다(Initial commit 이래). 기존 테스트는 전부 ID 와 이름이
**같은** 스텁이라 이 결함을 한 번도 건드리지 못했다 — 여기서는 ID 와 이름이 **어긋난** 스텁으로 잰다.

같은 이름 블록이 여럿(정본이 한 함수를 두 절에)이면 **축별**로 갈린 축만 막는다(리뷰 W3). ID 는 판정에 쓰지 않는다(리뷰 W1 —
"무의미하다고 선언한 키" 로 안전값 충돌을 조용히 결정하지 않는다). 자리표시자(TBD·N/A)는 의견이 아니다(리뷰 W2).
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("docx")


@pytest.fixture(autouse=True)
def _no_repo_template(monkeypatch, tmp_path):
    """저장소 기본 템플릿(430 heading)·고정 참조(40MB)를 끌어오지 않는다 — `test_uds_reference_precedence` 와 같은 이유."""
    import config
    monkeypatch.setattr(config, "resolve_uds_template_path", lambda: "", raising=False)
    monkeypatch.setattr(config, "UDS_REF_SUDS_PATH", str(tmp_path / "no_such_reference.docx"), raising=False)


def _fn(fid: str, name: str, **over):
    base = {
        "id": fid, "name": name, "prototype": f"void {name}(void);", "description": "설명",
        "asil": "TBD", "asil_source": "", "related": "", "related_source": "",
        "inputs": [], "outputs": [], "precondition": "", "globals_global": [], "globals_static": [],
        "called": "", "calling": "", "logic": "",
    }
    base.update(over)
    return base


def _payload(*fns, project="HDPDM01_PDS64_RD"):
    return {"project_name": project, "function_details": {f["id"]: f for f in fns}}


def _run(tmp_path, monkeypatch, ref_map, payload):
    """가짜 정본(같은 프로젝트 이름) + 파싱 결과 monkeypatch → 폴백 모드로 생성 → 보강 사이드카·통계."""
    import docx

    import config
    from report_gen import docx_builder
    from report_gen.docx_builder import enriched_function_details_path, generate_uds_docx

    ref_path = tmp_path / "(HDPDM01_SUDS) Software Unit Design Specification.docx"
    docx.Document().save(str(ref_path))
    monkeypatch.setattr(config, "UDS_REF_SUDS_PATH", str(ref_path), raising=False)
    monkeypatch.setattr(docx_builder, "_extract_function_info_from_docx", lambda _doc: ref_map)
    out = tmp_path / "uds.docx"
    stats: dict = {}
    generate_uds_docx(None, payload, str(out), stats_out=stats)
    side = json.loads(enriched_function_details_path(str(out)).read_text(encoding="utf-8"))
    return side["function_details"], stats["reference_suds"]


_MATCH_KEYS = {"by_name", "by_name_and_id", "id_collision_blocks", "unmatched_blocks", "unnamed_blocks",
               "blocked_axes", "ambiguous_names", "ambiguous_sample"}


class TestNameIsTheKey:
    def test_id_collision_does_not_pollute_either_function(self, tmp_path, monkeypatch):
        """정본 SwUFn_0001 = beta, 생성본 SwUFn_0001 = alpha — 옛 규칙이면 alpha 가 beta 의 ASIL·Related·인터페이스를 받는다."""
        ref_map = {
            "SwUFn_0001": {"name": "beta", "asil": "D", "related": "SwR_9", "inputs": ["[IN] x : U8"],
                           "outputs": ["[OUT] y : U8"], "called": "beta_helper", "precondition": "P-beta"},
            "SwUFn_0002": {"name": "alpha", "asil": "A", "related": "SwR_1", "inputs": ["[IN] a : U8"],
                           "outputs": ["[OUT] b : U8"], "called": "alpha_helper", "precondition": "P-alpha"},
        }
        fd, ref = _run(tmp_path, monkeypatch, ref_map, _payload(_fn("SwUFn_0001", "alpha"), _fn("SwUFn_0002", "beta")))
        a, b = fd["SwUFn_0001"], fd["SwUFn_0002"]
        assert (a["asil"], a["related"], a["inputs"], a["outputs"], a["called"], a["precondition"]) == \
            ("A", "SwR_1", ["[IN] a : U8"], ["[OUT] b : U8"], "alpha_helper", "P-alpha")
        assert (b["asil"], b["related"], b["inputs"], b["outputs"], b["called"], b["precondition"]) == \
            ("D", "SwR_9", ["[IN] x : U8"], ["[OUT] y : U8"], "beta_helper", "P-beta")
        assert (a["asil_source"], b["asil_source"]) == ("reference", "reference")
        m = ref["matching"]
        assert (m["by_name"], m["by_name_and_id"], m["id_collision_blocks"]) == (2, 0, 2)
        assert ref["safety_fields_kept_conflict"] == {}, "같은 함수에 정본 블록이 두 번 오지 않으므로 정본 자기 충돌은 0"

    def test_block_without_a_name_is_skipped_even_if_its_id_exists(self, tmp_path, monkeypatch):
        """ID 만 있는 블록은 매칭 근거가 없다 — 적용하지 않고 `unnamed_blocks` 로 센다."""
        fd, ref = _run(tmp_path, monkeypatch, {"SwUFn_0001": {"asil": "D", "related": "SwR_9"}},
                       _payload(_fn("SwUFn_0001", "alpha")))
        # 뒤의 잔여 처리가 빈 칸을 TBD/default 로 표시하므로 "정본이 아니다" 로 잰다
        assert fd["SwUFn_0001"]["asil"] == "TBD" and fd["SwUFn_0001"]["asil_source"] != "reference"
        assert ref["safety_fields_applied"] == 0
        assert (ref["matching"]["unnamed_blocks"], ref["matching"]["by_name"]) == (1, 0)

    def test_name_and_id_agreeing_is_counted_separately(self, tmp_path, monkeypatch):
        fd, ref = _run(tmp_path, monkeypatch, {"SwUFn_0001": {"name": "alpha", "asil": "A"}},
                       _payload(_fn("SwUFn_0001", "alpha")))
        assert fd["SwUFn_0001"]["asil"] == "A"
        m = ref["matching"]
        assert (m["by_name_and_id"], m["by_name"], m["id_collision_blocks"]) == (1, 0, 0)

    def test_block_whose_name_is_not_in_payload_is_counted_not_applied(self, tmp_path, monkeypatch):
        """정본에만 있는 함수(실측 37) — ID 가 우연히 생성본에 있어도 그 함수는 아니다."""
        fd, ref = _run(tmp_path, monkeypatch, {"SwUFn_0001": {"name": "zeta", "asil": "D"}},
                       _payload(_fn("SwUFn_0001", "alpha")))
        assert fd["SwUFn_0001"]["asil"] == "TBD"
        assert (ref["matching"]["unmatched_blocks"], ref["safety_fields_applied"]) == (1, 0)

    def test_name_match_tolerates_case_and_whitespace(self, tmp_path, monkeypatch):
        fd, ref = _run(tmp_path, monkeypatch, {"SwUFn_0009": {"name": "  ALPHA ", "asil": "B"}},
                       _payload(_fn("SwUFn_0001", "alpha")))
        assert (fd["SwUFn_0001"]["asil"], ref["matching"]["by_name"]) == ("B", 1)

    def test_matching_stats_shape_is_always_present(self, tmp_path, monkeypatch):
        _fd, ref = _run(tmp_path, monkeypatch, {}, _payload(_fn("SwUFn_0001", "alpha")))
        assert set(ref["matching"]) == _MATCH_KEYS
        assert all(v == 0 for k, v in ref["matching"].items() if k not in ("ambiguous_sample", "blocked_axes"))
        assert ref["matching"]["blocked_axes"] == {} and ref["matching"]["ambiguous_sample"] == []


class TestDuplicateNameBlocks:
    """정본이 한 함수를 두 절에 실었다(실측 kjpds02_pv: main·LINPHY0_Init·SCI0_Init·EEPROM 6 이 SwCom_35 에 사본)."""

    def test_agreeing_duplicates_apply_once_without_ambiguity(self, tmp_path, monkeypatch):
        ref_map = {"SwUFn_0101": {"name": "alpha", "asil": "A", "related": "SwR_1"},
                   "SwUFn_3563": {"name": "alpha", "asil": "ASIL A", "related": "SwR_1"}}
        fd, ref = _run(tmp_path, monkeypatch, ref_map, _payload(_fn("SwUFn_0005", "alpha")))
        assert (fd["SwUFn_0005"]["asil"], fd["SwUFn_0005"]["related"]) == ("A", "SwR_1")
        assert (ref["matching"]["ambiguous_names"], ref["matching"]["by_name"]) == (0, 2)
        assert ref["matching"]["blocked_axes"] == {} and ref["safety_fields_kept_conflict"] == {}

    def test_disagreeing_duplicates_apply_nothing_on_the_conflicting_axes_and_disclose(self, tmp_path, monkeypatch):
        """두 절이 A 와 QM 을 말하면 첫 절을 고르는 것은 침묵 판정 — 값을 두고 표본으로 공시한다."""
        ref_map = {"SwUFn_0101": {"name": "alpha", "asil": "A", "related": "SwR_1", "inputs": ["[IN] a"]},
                   "SwUFn_3563": {"name": "alpha", "asil": "QM", "related": "SwR_2", "inputs": ["[IN] b"]}}
        fd, ref = _run(tmp_path, monkeypatch, ref_map, _payload(_fn("SwUFn_0005", "alpha")))
        a = fd["SwUFn_0005"]
        # 뒤의 잔여 처리가 빈 Related 를 TBD 로 표시한다 — 어느 절의 값(SwR_1/SwR_2, [IN] a/b)도 없어야 한다
        assert (a["asil"], a["inputs"]) == ("TBD", []) and a["related"] in ("", "TBD"), "갈린 축은 어느 절의 값도 싣지 않는다"
        assert a["asil_source"] != "reference" and a["related_source"] != "reference"
        m = ref["matching"]
        assert m["ambiguous_names"] == 1 and m["by_name"] == 2
        assert m["blocked_axes"] == {"asil": 1, "related": 1, "inputs": 1}
        assert m["ambiguous_sample"] == [{
            "name": "alpha", "id": "SwUFn_0005", "conflicting": ["asil", "inputs", "related"],
            "blocks": [{"id": "SwUFn_0101", "asil": "A", "related": "SwR_1"},
                       {"id": "SwUFn_3563", "asil": "QM", "related": "SwR_2"}],
        }]
        assert ref["safety_fields_applied"] == 0

    def test_matching_id_does_not_settle_a_value_conflict(self, tmp_path, monkeypatch):
        """(리뷰 W1) 정본 번호는 생성 번호와 무관하다고 선언해 놓고 그 번호로 A/QM 을 고르면 근거 없는 하향이 침묵한다."""
        ref_map = {"SwUFn_1901": {"name": "alpha", "asil": "A", "related": "SwR_1"},
                   "SwUFn_3516": {"name": "alpha", "asil": "QM", "related": "SwR_2"}}
        fd, ref = _run(tmp_path, monkeypatch, ref_map, _payload(_fn("SwUFn_3516", "alpha")))
        a = fd["SwUFn_3516"]
        assert a["asil"] == "TBD" and a["asil_source"] != "reference" and a["related_source"] != "reference"
        m = ref["matching"]
        assert (m["ambiguous_names"], m["by_name_and_id"], m["by_name"]) == (1, 1, 1)

    def test_ambiguity_does_not_depend_on_block_order(self, tmp_path, monkeypatch):
        fwd = {"SwUFn_1901": {"name": "alpha", "asil": "A"}, "SwUFn_3516": {"name": "alpha", "asil": "QM"}}
        rev = dict(reversed(list(fwd.items())))
        for ref_map in (fwd, rev):
            fd, ref = _run(tmp_path, monkeypatch, ref_map, _payload(_fn("SwUFn_1901", "alpha")))
            assert fd["SwUFn_1901"]["asil_source"] != "reference" and ref["matching"]["ambiguous_names"] == 1

    def test_duplicates_differing_only_in_related_block_related_but_apply_asil(self, tmp_path, monkeypatch):
        """실측 9건 중 6건이 ASIL 은 같고 Related 만 다르다(EEPROM_* : SwCom_21 vs SwCom_35) — 갈린 축만 막는다(리뷰 W3)."""
        ref_map = {"SwUFn_2101": {"name": "alpha", "asil": "QM", "related": "SwCom_21", "precondition": "P"},
                   "SwUFn_3520": {"name": "alpha", "asil": "QM", "related": "SwCom_35", "precondition": "P"}}
        fd, ref = _run(tmp_path, monkeypatch, ref_map, _payload(_fn("SwUFn_3502", "alpha")))
        a = fd["SwUFn_3502"]
        assert (a["asil"], a["asil_source"], a["precondition"]) == ("QM", "reference", "P")
        assert a["related_source"] != "reference" and a["related"] in ("", "TBD")
        assert ref["matching"]["ambiguous_names"] == 1 and ref["matching"]["blocked_axes"] == {"related": 1}

    def test_duplicates_differing_only_in_interfaces_apply_safety_but_not_the_interfaces(self, tmp_path, monkeypatch):
        """(리뷰 W3) EEPROM 사본 절은 prototype 이 다르다(`EEPROM_TAddress` vs `_Const`) — inputs 만 막고 ASIL·Related 는 싣는다."""
        ref_map = {"SwUFn_2101": {"name": "alpha", "asil": "QM", "related": "SwCom_21", "inputs": ["[IN] Addr : EEPROM_TAddress"], "outputs": ["[OUT] r : U8"]},
                   "SwUFn_3520": {"name": "alpha", "asil": "QM", "related": "SwCom_21", "inputs": ["[IN] Addr : EEPROM_TAddress_Const"], "outputs": ["[OUT] r : U8"]}}
        fd, ref = _run(tmp_path, monkeypatch, ref_map, _payload(_fn("SwUFn_3502", "alpha")))
        a = fd["SwUFn_3502"]
        assert (a["asil"], a["related"], a["inputs"], a["outputs"]) == ("QM", "SwCom_21", [], ["[OUT] r : U8"])
        assert ref["matching"]["ambiguous_names"] == 0, "ASIL·Related 는 같으니 정본 품질 항목은 아니다"
        assert ref["matching"]["blocked_axes"] == {"inputs": 1}

    def test_placeholder_in_one_copy_is_not_an_opinion(self, tmp_path, monkeypatch):
        """(리뷰 W2) 사본 절의 ASIL 칸이 TBD 면 유효한 D 를 막지 않는다 — 적용 경로가 버리는 값은 판정 경로에서도 의견이 아니다."""
        ref_map = {"SwUFn_0101": {"name": "alpha", "asil": "D", "related": "SwR_1"},
                   "SwUFn_3563": {"name": "alpha", "asil": "TBD", "related": "N/A"}}
        fd, ref = _run(tmp_path, monkeypatch, ref_map, _payload(_fn("SwUFn_0005", "alpha")))
        assert (fd["SwUFn_0005"]["asil"], fd["SwUFn_0005"]["related"]) == ("D", "SwR_1")
        assert ref["matching"]["ambiguous_names"] == 0 and ref["matching"]["blocked_axes"] == {}

    def test_ambiguity_is_counted_once_per_function_not_per_block(self, tmp_path, monkeypatch):
        ref_map = {f"SwUFn_{i:04d}": {"name": "alpha", "asil": a} for i, a in ((101, "A"), (3563, "QM"), (4001, "B"))}
        _fd, ref = _run(tmp_path, monkeypatch, ref_map, _payload(_fn("SwUFn_0005", "alpha")))
        assert ref["matching"]["ambiguous_names"] == 1 and len(ref["matching"]["ambiguous_sample"]) == 1
        assert ref["matching"]["blocked_axes"] == {"asil": 1}


class TestResolverUnit:
    """`_resolve_reference_target` 단독 — 빌더 없이 계수 규칙만."""

    def _stats(self):
        return {"by_name": 0, "by_name_and_id": 0, "id_collision_blocks": 0, "unmatched_blocks": 0, "unnamed_blocks": 0,
                "blocked_axes": {}, "ambiguous_names": 0, "ambiguous_sample": []}

    def test_collision_is_not_counted_when_the_id_function_has_the_same_name(self):
        """payload 에 같은 이름이 둘(정적 함수 동명)이고 ID 가 그중 다른 하나를 가리켜도 충돌은 아니다."""
        from report_gen.docx_builder import _resolve_reference_target

        f1, f2 = _fn("SwUFn_0001", "alpha"), _fn("SwUFn_0002", "alpha")
        fd = {"SwUFn_0001": f1, "SwUFn_0002": f2}
        ref_map = {"SwUFn_0001": {"name": "alpha", "asil": "A"}}
        st = self._stats()
        got, blocked = _resolve_reference_target("SwUFn_0001", ref_map["SwUFn_0001"], fd, {"alpha": f2}, {"alpha": ["SwUFn_0001"]}, ref_map, st, set())
        assert got is f2 and blocked == set() and st["id_collision_blocks"] == 0 and st["by_name"] == 1

    def test_raw_lowercase_name_index_is_a_fallback(self):
        """(리뷰 I6) 정규화형(`alpha`)이 인덱스에 없고 raw 소문자(`alpha()`)만 있을 때 — 두 키가 실제로 갈리는 경우."""
        from report_gen.docx_builder import _resolve_reference_target

        f1 = _fn("SwUFn_0001", "alpha()")
        st = self._stats()
        got, _ = _resolve_reference_target("R1", {"name": "alpha()"}, {"SwUFn_0001": f1}, {"alpha()": f1}, {"alpha": ["R1"]}, {"R1": {"name": "alpha()"}}, st, set())
        assert got is f1 and st["by_name"] == 1

    def test_non_dict_index_means_unmatched_not_crash(self):
        from report_gen.docx_builder import _resolve_reference_target

        st = self._stats()
        assert _resolve_reference_target("R1", {"name": "alpha"}, {}, None, {"alpha": ["R1"]}, {}, st, set()) == (None, set())
        assert st["unmatched_blocks"] == 1

    @pytest.mark.parametrize("axis,value,expected", [
        ("asil", "ASIL B", "B"), ("asil", "TBD", ""), ("asil", "N/A", ""), ("asil", "void f(void)", ""),
        ("related", "SwR_2, SwR_1", "SWR_1,SWR_2"), ("related", "TBD", ""), ("related", "-", ""), ("related", "SwR_1, TBD", "SWR_1"),
        ("inputs", ["[IN] a : U8", " [IN]  b "], "[IN] a : U8\n[IN] b"), ("inputs", [], ""),
        ("precondition", " N/A ", ""), ("precondition", "power on", "power on"),
    ])
    def test_reference_opinion_ignores_placeholders(self, axis, value, expected):
        from report_gen.docx_builder import _reference_opinion
        assert _reference_opinion(value, axis) == expected
