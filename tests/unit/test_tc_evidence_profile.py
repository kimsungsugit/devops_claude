"""R78 — 시험 **근거** 프로파일(`recommended`): 물량은 그대로, 기대결과를 관측 가능하게.

R75 가 만든 `tc_profile` 은 **물량** 축이었다. 2026-09-20 산출물 실측에서 드러난 최대 결손은
물량이 아니라 근거였다 — STS 스텝 8,130행 중 기대결과가 관측 가능한 것이 26%(구체값 685 +
경로/분기 1,483)뿐이고, `기대 결과와 일치` 1,128 · 행동 반복 840 · 서술 3,048 은 **무엇을 보고
합격인지 말하지 않는다**.

그래서 중간 단계를 둔다:  reference ⊂ recommended ⊂ extended
                          (물량 기본)   (물량 기본 +      (물량 확장 +
                                         근거 보강)        근거 보강)

## 이 파일이 지키는 것

1. **포함 관계** — `recommended` 는 TC 를 **늘리지 않는다**(물량 불변). 늘리면 두 문서를 나란히 못 본다.
2. **지어내지 않음** — 반환 타입도 전역도 모르면 문장을 그대로 두고 그 수를 공시한다.
   (뮤테이션: 모를 때도 `반환값: ()` 를 내면 여기서 실패해야 한다)
3. **음성 대조군** — 기본값에서는 기대결과 문장이 한 글자도 안 바뀐다.
4. **표기 결함** — `ASIL ASIL A` · Pre 입력 토큰 중복. 옵션이 아니라 **버그**라 기본값에서도 고친다.
5. **SITS 라벨 ↔ 산출 일치** — ABV 는 경계 sub-case 를 **실제로 낸** 흐름에만 붙는다.
6. **어휘 정본** — 조합이 늘어도 코드 집합(AOR·AEC·ABV)은 그대로여야 한다(평가기 분모).
"""
from __future__ import annotations

import copy

import pytest

from generators import sits as S
from generators.sts import (
    _build_tc_dict,
    _drain_evidence_marks,
    _ensure_min_steps,
    _observation_basis,
    generate_test_cases,
)
from generators.tc_profile import (
    TC_PROFILE_EXTENDED,
    TC_PROFILE_RECOMMENDED,
    TC_PROFILE_REFERENCE,
    is_evidence_enriched,
    is_extended,
    normalize_tc_profile,
)

_PROFILES = ("", "reference", TC_PROFILE_RECOMMENDED, TC_PROFILE_EXTENDED)


# ── 프로파일 값 ──────────────────────────────────────────────────────────────

class TestProfileValue:
    @pytest.mark.parametrize("raw, prof", [
        ("", TC_PROFILE_REFERENCE), ("reference", TC_PROFILE_REFERENCE),
        ("recommended", TC_PROFILE_RECOMMENDED), (" RECOMMENDED ", TC_PROFILE_RECOMMENDED),
        ("extended", TC_PROFILE_EXTENDED),
        ("recommneded", TC_PROFILE_REFERENCE), (None, TC_PROFILE_REFERENCE),
    ])
    def test_recommended_joins_the_same_normalizer(self, raw, prof):
        assert normalize_tc_profile(raw)[0] == prof
        assert normalize_tc_profile("recommneded")[1] == "recommneded", "못 알아본 값은 버리지 않고 돌려준다"

    def test_the_two_axes_are_separate_predicates(self):
        """물량(`is_extended`)과 근거(`is_evidence_enriched`)는 **다른 축**이다.

        한 술어로 묶으면 `recommended` 가 상한까지 풀어 "물량은 그대로" 약속이 깨진다.
        기존 호출부 3곳(`sts.generate_test_cases`·`suts.generate_suts`·`sits.resolve_profile_caps`)이
        `is_extended` 로 상한을 푼다 — 그래서 이 술어의 뜻은 `recommended` 가 생겨도 바뀌면 안 된다.
        """
        assert [is_extended(p) for p in _PROFILES] == [False, False, False, True]
        assert [is_evidence_enriched(p) for p in _PROFILES] == [False, False, True, True]

    def test_recommended_is_inside_extended(self):
        """포함 관계 — 확장은 권장을 **담는다**. 둘 다 근거 보강이 켜져야 그 말이 참이다."""
        assert is_evidence_enriched(TC_PROFILE_EXTENDED) and is_evidence_enriched(TC_PROFILE_RECOMMENDED)
        assert not is_evidence_enriched(TC_PROFILE_REFERENCE)


# ── STS 기대결과 ─────────────────────────────────────────────────────────────

#: 분기 하나 — 흐름 있는 함수를 만들 때 쓴다(`_generate_steps_from_flow` 의 분기 TC 경로).
_IF = [{"type": "if", "condition": "n > 10", "true_body": [{"type": "call", "name": "A"}],
        "false_body": [{"type": "call", "name": "B"}]}]


def _fn(name="Fn", *, output=None, globals_=(), inputs=("[IN] U8 n",), flow=()):
    fi = {"id": name, "name": name, "prototype": f"{output or 'void'} {name}(U8 n)",
          "inputs": list(inputs), "outputs": [], "calls_list": [], "logic_flow": list(flow)}
    if output is not None:
        fi["output"] = output
    if globals_:
        fi["globals_global"] = list(globals_)
    return fi


def _expect(fi, *, enrich):
    """생성 → **문서 조립 시점의 계수**까지 한 번에. 계수는 표식을 떼면서 한다(`_drain_evidence_marks`)."""
    stats: dict = {}
    steps = _ensure_min_steps([], fi, enrich=enrich)
    _drain_evidence_marks(steps, stats)
    assert not any(k.startswith("_") for st in steps for k in st), "표식은 문서에 나가기 전에 떼야 한다"
    return [(s["action"], s["expected"]) for s in steps], stats


class TestExpectedResultEvidence:
    def test_return_type_becomes_the_observation_target(self):
        """`기대 결과와 일치` 는 무엇을 보고 합격인지 없다 — 반환이 있으면 그것이 관측 대상이다."""
        base, st0 = _expect(_fn(output="U16"), enrich=False)
        enr, st1 = _expect(_fn(output="U16"), enrich=True)
        assert ("출력/반환값 확인", "기대 결과와 일치 (U16)") in base
        assert ("출력/반환값 확인", "반환값: (U16)") in enr
        assert ("Fn() 호출", "Fn 반환값 획득 (U16)") in enr, "호출 스텝도 무엇을 얻는지 말한다"
        assert ("Fn() 호출", "Fn 정상 실행 확인") in base
        assert st0 == {} and st1["expected_enriched"] == 2 and st1.get("expected_no_basis", 0) == 0
        assert not any("정상 실행 확인" in e for _, e in enr), "보강본엔 무의미한 문장이 남지 않는다"

    def test_void_function_with_globals_observes_the_globals(self):
        # ⚠ 생산자가 내는 shape 를 쓴다 — 방향 태그가 붙은 **선언 텍스트**다.
        #   태그 없는 dict 는 방향을 모르니 근거가 아니다(아래 방향 시험이 따로 고정한다).
        fi = _fn(output="void", globals_=["[OUT] g_State", "[INOUT] g_Cnt", "[OUT] g_Third"])
        enr, st = _expect(fi, enrich=True)
        assert ("출력/반환값 확인", "글로벌 g_State, g_Cnt 값 변화 관측") in enr, "전역은 앞 2개까지"
        assert ("Fn() 호출", "Fn 실행 후 글로벌 g_State, g_Cnt 갱신") in enr, "반환이 없어도 전역이 근거다"
        assert st["expected_enriched"] == 2 and st.get("expected_no_basis", 0) == 0
        assert "g_Third" not in str(enr), "셋째 전역은 칸을 넘치게 하므로 싣지 않는다"

    @pytest.mark.parametrize("fi", [
        _fn(),                                    # output 키 자체가 없다
        _fn(output="void"),                       # 반환 없음 + 전역 없음
        _fn(output="None"),
        _fn(output="  "),
        _fn(output="void", globals_=[{"name": ""}, {"nom": "오타키"}]),   # 이름을 못 읽는 전역
    ])
    def test_no_basis_means_the_sentence_is_left_alone(self, fi):
        """**지어내지 않는다.** 근거가 없으면 문장을 그대로 두고 그 수를 센다.

        뮤테이션: 근거 없이도 `반환값: ()` / `글로벌  값 변화 관측` 을 내면 여기서 죽는다.
        """
        base, _ = _expect(copy.deepcopy(fi), enrich=False)
        enr, st = _expect(copy.deepcopy(fi), enrich=True)
        assert enr == base, "근거가 없으면 보강본과 기본본이 **글자까지** 같다"
        assert st.get("expected_enriched", 0) == 0 and st["expected_no_basis"] == 2, "두 스텝 다 근거 없음으로 센다"
        assert not any("반환값:" in e or "글로벌" in e for _, e in enr)

    def test_global_names_are_not_raw_declaration_text(self):
        """전역 원소는 `"[OUT] REG_LP0DR"` 같은 **선언 텍스트**다 — 방향 태그·주석 꼬리가 칸에 실리면 안 된다.

        라이브 실측(HDPDM01)에서 `글로벌 [INDIRECT] tbl (size: 8) (idx: 7, *(resp… 값 변화 관측` 로
        나갔다. 이름만 뽑는 단일 출처는 `_split_param_decl` 이다.
        """
        fi = _fn(output="void", globals_=["[OUT] REG_LP0DR",
                                          "[INOUT] lin_timeout_val (size: 8) (idx: 7, x)"])
        enr, st = _expect(fi, enrich=True)
        exp = [e for a, e in enr if a == "출력/반환값 확인"][0]
        assert exp == "글로벌 REG_LP0DR, lin_timeout_val 값 변화 관측", exp
        assert "[" not in exp and "(" not in exp and st["expected_enriched"] == 2

    @pytest.mark.parametrize("globs, want", [
        # 쓰기 방향이 하나라도 있으면 그것만 고른다
        (["[OUT] g_State"], ("globals", "g_State")),
        (["[INOUT] g_Cnt"], ("globals", "g_Cnt")),
        (["[IN] g_Flag", "[OUT] g_State", "[INOUT] g_Cnt"], ("globals", "g_State, g_Cnt")),
        # 읽기 전용뿐이면 **근거 없음** — 안 일어나는 일을 단언하지 않는다
        (["[IN] g_Flag"], ("", "")),
        (["[IN] g_A", "[INDIRECT] g_B (size: 8)", "[INDIRECT2] g_C"], ("", "")),
        # 태그가 없으면 방향을 모른다 → 근거 없음("모르면 안 쓴다")
        (["g_Plain"], ("", "")),
        ([{"name": "g_Dict"}], ("", "")),
    ])
    def test_only_written_globals_are_an_observation_target(self, globs, want):
        """`[IN]` 은 **읽기만** 한다는 뜻이다(`uds_generator`: lhs 없으면 IN).

        거기에 "갱신 / 값 변화 관측" 을 적으면 감사 문서가 일어나지 않는 일을 단언한다.
        실측(HDPDM01 447함수): globals 를 근거로 삼은 370 중 **164(44%)가 고른 전역이
        전부 읽기 전용**이었다 — deep 리뷰가 잡은 Critical.

        방향 → 의미 판정은 `function_analyzer._TAG_TO_COLUMNS` 단일 출처를 쓴다.
        ⚠ 이 파일의 `_PARAM_DIR_TAG_RE` 는 `IN|OUT|INOUT` 셋만 알아 `INDIRECT` 계열을
          "태그 없음" 으로 떨어뜨린다 — 그래서 그쪽을 쓰면 안 된다.
        """
        fi = _fn(output="void")
        fi["globals_global"] = list(globs)
        assert _observation_basis(fi) == want

    def test_read_only_globals_leave_the_sentence_alone(self):
        """문장 축에서도 확인 — 읽기 전용뿐이면 기본본과 **글자까지** 같다."""
        fi = _fn(output="void")
        fi["globals_global"] = ["[IN] g_Flag", "[INDIRECT] g_Tbl (size: 8)"]
        base, _ = _expect(copy.deepcopy(fi), enrich=False)
        enr, st = _expect(copy.deepcopy(fi), enrich=True)
        assert enr == base and st["expected_no_basis"] == 2
        assert not any("갱신" in e or "값 변화 관측" in e for _, e in enr)

    @pytest.mark.parametrize("out", ["N/A", "n/a", "-", "TBD", "?", "unknown", "void", "None", " "])
    def test_placeholder_return_types_are_not_an_observation_target(self, out):
        """`반환값: (N/A)` 는 근거가 아니다.

        `out_hint` 시절엔 힌트를 안 붙이는 조건이라 `void`/`None` 둘로 충분했는데,
        지금은 **단언**을 만드는 자리라 파서가 못 읽어 채운 자리표시자까지 걸러야 한다.
        """
        assert _observation_basis(_fn(output=out)) == ("", "")
        enr, st = _expect(_fn(output=out), enrich=True)
        assert st["expected_no_basis"] == 2 and not any("반환값:" in e for _, e in enr)

    def test_negative_control_default_profile_changes_nothing(self):
        """음성 대조군 — 기본값에서는 스텝이 한 글자도 안 바뀐다."""
        fd = {"F1": _fn("A", output="U16"), "F2": _fn("B", output="void", globals_=[{"name": "g_X"}])}
        reqs = [{"id": "SwTR_0001", "req_type": "TR"}]
        mapping = {"SwTR_0001": ["F1", "F2"]}

        def _run(profile):
            st: dict = {}
            tcs = generate_test_cases(copy.deepcopy(reqs), copy.deepcopy(fd), dict(mapping),
                                      {"max_tc_per_req": 9, "tc_profile": profile}, stats_out=st)
            return [(t["id"], t["title"], [(s["action"], s["expected"]) for s in t["steps"]]) for t in tcs], st

        base, st0 = _run("")
        ref, _ = _run("reference")
        rec, st1 = _run(TC_PROFILE_RECOMMENDED)
        assert ref == base, "`reference` 는 미설정과 완전히 같다"
        assert st0["expected_enriched"] == st0["expected_no_basis"] == 0, "기본은 보강도 미보강 계수도 0"
        assert rec != base, "전제: 이 입력에는 보강할 근거가 있다(없으면 이 시험이 아무것도 안 잰다)"
        assert st1["expected_enriched"] > 0
        assert not any("반환값:" in e for _, _, steps in base for _, e in steps)

    def test_recommended_does_not_change_how_many_test_cases_there_are(self):
        """**물량 불변** — 근거만 올린다. TC 수·ID·제목·요구 배치가 전부 같아야 한다.

        라이브 실측(HDPDM01, 2026-09-21): 기본 449 TC / 권장 449 TC — 같은 수에
        `expected_enriched` 177 · `expected_no_basis` 73 이 붙었다.
        """
        fd = {f"F{i}": _fn(f"S_Fn_{i}", output="U16") for i in range(1, 7)}
        reqs = [{"id": "SwTR_0001", "req_type": "TR"}, {"id": "SwTR_0002", "req_type": "TR"}]
        mapping = {"SwTR_0001": ["F1", "F2", "F3"], "SwTR_0002": ["F4", "F5", "F6"]}

        def _run(profile):
            st: dict = {}
            tcs = generate_test_cases(copy.deepcopy(reqs), copy.deepcopy(fd), dict(mapping),
                                      {"max_tc_per_req": 2, "tc_profile": profile}, stats_out=st)
            return tcs, st

        base, st0 = _run("")
        rec, st1 = _run(TC_PROFILE_RECOMMENDED)
        ext, st2 = _run(TC_PROFILE_EXTENDED)
        assert len(rec) == len(base) > 0
        assert [(t["id"], t["srs_id"], t["title"]) for t in rec] == [(t["id"], t["srs_id"], t["title"]) for t in base]
        assert st1["tc_profile"] == TC_PROFILE_RECOMMENDED and st1["extended_tcs"] == st0["extended_tcs"] == 0
        assert len(ext) > len(base) and st2["extended_tcs"] > 0, "확장은 물량도 푼다 — 두 축이 갈렸음을 라이브로 고정"

    def test_the_reported_count_equals_what_is_in_the_document(self):
        """공시 수 = **문서에 실린 수**. 만든 수가 아니다.

        생성기는 문서에 안 실릴 스텝도 만든다 — `_generate_simple_steps` 는 TC1·TC2·TC3 셋을
        내는데 흐름이 있는 함수에서는 **경계 TC 하나만** 골라 쓰고, 요구당 상한에 걸려 통째로
        빠지는 TC 도 있다. 만든 자리에서 세면 두 수가 어긋난다(실측: 만든 수 298 vs 문서 440).

        뮤테이션: 계수를 `_generate_simple_steps` 안으로 되돌리면 여기서 죽는다.
        """
        # ⚠ **흐름 있는 함수를 섞는다.** 흐름이 있으면 경계 TC 가 `_generate_simple_steps` 가
        #   낸 셋 중 **하나만** 골라 들어온다 — 만든 수와 실린 수가 갈리는 바로 그 경로다.
        fd = {f"F{i}": _fn(f"S_Fn_{i}", output=("U16" if i % 2 else None),
                           globals_=([{"name": f"g_{i}"}] if i % 3 == 0 else []),
                           flow=(_IF if i % 2 == 0 else []))
              for i in range(1, 8)}
        reqs = [{"id": "SwTR_0001", "req_type": "TR"}]
        mapping = {"SwTR_0001": list(fd)}

        def _run(profile, max_tc):
            st: dict = {}
            tcs = generate_test_cases([dict(r) for r in reqs], copy.deepcopy(fd), dict(mapping),
                                      {"max_tc_per_req": max_tc, "tc_profile": profile}, stats_out=st)
            return tcs, st

        for max_tc in (1, 2, 5, 9):
            base, _ = _run("", max_tc)
            rec, st = _run(TC_PROFILE_RECOMMENDED, max_tc)
            assert len(rec) == len(base), max_tc
            # 문서에서 **실제로 달라진 기대결과 줄** 수를 센다.
            # ⚠ `유효 범위 미만` 은 보강이 **덧붙인** 스텝이라 위치가 밀린다 — 빼고 맞춘다.
            #   (안 빼면 밀린 자리가 전부 "바뀐 것" 으로 세어져 수가 부풀린다)
            changed, added = 0, 0
            for tb, tr in zip(base, rec, strict=True):
                rs = []
                for st_ in tr["steps"]:
                    if "유효 범위 미만" in st_["action"] or "범위 미만 입력 방어" in st_["expected"]:
                        added += 1
                    else:
                        rs.append(st_)
                assert len(rs) == len(tb["steps"]), (max_tc, tb["id"])
                changed += sum(1 for sb, sr in zip(tb["steps"], rs, strict=True) if sb["expected"] != sr["expected"])
            assert st["expected_enriched"] == changed, (max_tc, st["expected_enriched"], changed)
            # 표식이 산출물로 새지 않는다
            assert not any(k.startswith("_") for t in rec for step in t["steps"] for k in step), max_tc

    def test_the_counts_reach_the_quality_report(self):
        """보고를 **추가했다** 와 보고가 **도달한다** 는 다른 문제다 — stats 에 실제로 실리는지 본다."""
        fd = {"F1": _fn("A", output="U16"), "F2": _fn("B", output="void")}
        st: dict = {}
        generate_test_cases([{"id": "SwTR_0001", "req_type": "TR"}], fd, {"SwTR_0001": ["F1", "F2"]},
                            {"max_tc_per_req": 9, "tc_profile": TC_PROFILE_RECOMMENDED}, stats_out=st)
        assert st["expected_enriched"] > 0 and st["expected_no_basis"] > 0, "두 축이 다 실린다"
        assert isinstance(st["expected_enriched"], int) and isinstance(st["expected_no_basis"], int)


# ── STS 경계값 하한(min_inv) ─────────────────────────────────────────────────

class TestLowerBoundStep:
    def _tcs(self, profile, inputs=("[IN] U8 n",)):
        fd = {"F1": _fn("A", output="U16", inputs=inputs)}
        return generate_test_cases([{"id": "SwTR_0001", "req_type": "TR"}], fd, {"SwTR_0001": ["F1"]},
                                   {"max_tc_per_req": 9, "tc_profile": profile})

    def _actions(self, tcs):
        return [s["action"] for t in tcs for s in t["steps"]]

    def test_lower_bound_violation_appears_only_when_enriched(self):
        """BVA 6점 중 이 문서는 min·max·max_inv 셋만 썼다. `min_inv` 는 `_TYPE_BOUNDARIES` 에 **이미 있다**."""
        base = self._actions(self._tcs(""))
        rec = self._actions(self._tcs(TC_PROFILE_RECOMMENDED))
        assert not any("유효 범위 미만" in a for a in base)
        assert any("유효 범위 미만" in a for a in rec)
        assert sum("유효 범위 초과" in a for a in rec) == sum("유효 범위 초과" in a for a in base), "기존 축은 그대로"

    def test_unknown_typed_input_gets_no_invented_lower_bound(self):
        """경계를 모르는 변수만 있으면 붙이지 않는다 — 선언 텍스트만 나열한 '범위 미만' 은 시험이 아니다."""
        rec = self._actions(self._tcs(TC_PROFILE_RECOMMENDED, inputs=("[IN] void *p",)))
        assert not any("유효 범위 미만" in a for a in rec)


# ── 표기 결함 — 옵션이 아니라 버그 ───────────────────────────────────────────

def _tc(req, steps):
    return _build_tc_dict(tc_id="SwTC_001", req=req, steps=steps, func_name="Fn",
                          test_method="RBT", gen_method="AOR", test_env="SwTE_01",
                          is_safety=True, review_only=False)


class TestNotationDefects:
    @pytest.mark.parametrize("raw, want", [
        ("ASIL A", "ASIL A 안전 조건 충족"), ("ASIL D", "ASIL D 안전 조건 충족"),
        ("A", "ASIL A 안전 조건 충족"), ("asil b", "ASIL B 안전 조건 충족"),
        ("ASIL-C", "ASIL C 안전 조건 충족"),
    ])
    def test_asil_prefix_is_not_written_twice(self, raw, want):
        """`project_config["asil_level"]` 이 `"ASIL A"` 형식이라 f-string 이 `ASIL ASIL A` 를 냈다(실측 571/2,209 = 25%)."""
        pre = _tc({"id": "SwTR_0001", "req_type": "TR", "asil": raw}, [{"action": "a", "expected": "e"}])["precondition"]
        assert want in pre and "ASIL ASIL" not in pre

    def test_unknown_grade_keeps_its_original_text(self):
        """미상 등급은 정규화가 None 을 낸다 — 그때만 원문을 그대로 둔다(지어내지 않는다)."""
        pre = _tc({"id": "SwTR_0001", "req_type": "TR", "asil": "Z급"}, [{"action": "a", "expected": "e"}])["precondition"]
        assert "Z급" in pre and "ASIL ASIL" not in pre

    def test_input_tokens_are_not_repeated_in_the_precondition(self):
        """TC2 는 최솟값·최댓값 두 스텝이 같은 변수를 쓴다 — 그대로 모으면 `[:4]` 상한을 중복이 채워 다른 변수를 밀어낸다."""
        steps = [{"action": "입력 설정 (경계 최솟값): n=0, m=0", "expected": "e"},
                 {"action": "입력 설정 (경계 최댓값): n=255, m=255", "expected": "e"},
                 {"action": "입력 설정 (유효 범위 초과): k=256", "expected": "e"}]
        pre = _tc({"id": "SwTR_0001", "req_type": "TR"}, steps)["precondition"]
        assert pre.count("n=") <= 1 and pre.count("m=") <= 1
        assert "k" in pre, "중복을 뺀 자리에 밀려나 있던 변수가 들어온다"

    @pytest.mark.parametrize("profile", _PROFILES)
    def test_both_defects_are_fixed_in_every_profile(self, profile):
        """버그 수정이므로 **기본값에서도** 적용된다 — 옵션 뒤에 숨기지 않는다."""
        fd = {"F1": _fn("A", inputs=("[IN] U8 n",))}
        tcs = generate_test_cases([{"id": "SwTR_0001", "req_type": "TR", "asil": "ASIL D"}], fd,
                                  {"SwTR_0001": ["F1"]}, {"max_tc_per_req": 9, "tc_profile": profile})
        assert tcs
        for t in tcs:
            pre = t["precondition"]
            assert "ASIL ASIL" not in pre, profile
            if "입력: " in pre:
                toks = [x.split("=")[0] for x in pre.split("입력: ")[-1].split(", ")]
                assert len(toks) == len(set(toks)), (profile, pre)


# ── SITS — 경계값은 **진단**이다. 라벨은 안 바꾼다 ──────────────────────────

def _flow(name, ivars, iraws=None, expected=("u8Result",)):
    return {"entry_fn": name, "call_chain": f"main -> {name}", "module_name": "m",
            "input_vars": list(ivars), "input_raws": list(iraws or ivars),
            "expected_vars": list(expected), "expected_raws": list(expected),
            "related_ids": ["SwCom_01"], "asil": "ASIL B", "logic_flow": [], "cross_calls": []}


_F_BV = _flow("Fn_Bv", ["u8Speed"], ["[IN] U8 u8Speed"])
_F_NOIO = _flow("Fn_NoIo", [], [], expected=[])


class TestSitsGenLabelIsNotTouched:
    """R78 은 여기에 `AOR, ABV, AEC` 를 붙이려다 **되돌렸다**. 이 반의 시험이 그 결정을 고정한다.

    되돌린 사유 3건(`generators/sits.py` 의 `_SITS_BV_MIN_DISTINCT` 블록에 전문):
      ① 붙이려던 문자열이 **두 정본 어디에도 0건** — 지금 기본값은 KJPDS02 와 100% 일치한다
      ② 판정이 `max_subcases` 의 **계단 함수** — TC 를 하나도 가르지 못한다
      ③ sub-case 를 **생성기 자신이 `EC…`(등가분할)** 이라 부른다. 재해석하면
         `method_diversity_pct` 가 66.67→100.0 이 되는데 문서는 한 글자도 안 바뀐다
    """

    def _itcs(self, profile, flows=None, **kw):
        return S.generate_itc_list([copy.deepcopy(f) for f in (flows or [_F_BV, _F_NOIO])],
                                   max_subcases=7, **kw)

    @pytest.mark.parametrize("profile", _PROFILES)
    def test_the_gen_column_follows_the_reference_pairing_in_every_profile(self, profile):
        """KJPDS02 정본: `REQ, IFT`↔`AOR, AEC` 49 · `FI`↔`AOR/ABV` 5 — **어느 프로파일에서도** 이 짝이다."""
        labels = {S._sits_gen_method_for_itc(t) for t in self._itcs(profile)}
        assert labels == {S._SITS_GEN_DEFAULT}, profile

    def test_no_profile_flag_leaks_into_the_test_cases(self):
        """itc 는 중간 JSON 과 영향도 초안으로 흘러간다 — 쓰지 않는 키를 남기면 거기서 새어나간다."""
        for profile in _PROFILES:
            for t in self._itcs(profile):
                assert "gen_evidence" not in t, profile
                assert not any(k.startswith("_") for k in t), profile

    def test_fault_injection_keeps_its_own_pairing(self):
        fi = [dict(_F_BV, fi_design_id="SwFn_07")]
        got = [S._sits_gen_method_for_itc(t) for t in self._itcs("", flows=[_F_BV], fi_flows=fi)]
        assert S._SITS_GEN_BOUNDARY in got and S._SITS_GEN_DEFAULT in got

    def test_writer_and_quality_report_read_the_same_source(self):
        """한쪽은 내부 라벨, 한쪽은 짝을 세던 결함(R76 N87)이 되살아나지 않게 — 분포는 **문서에 쓰는 값** 이다.

        값 자체는 안 바뀌지만 **자리를 하나로 모은 것**이 이번 변경의 본체다.
        """
        itcs = self._itcs("")
        dist = S.generate_sits_quality_report(itcs)["gen_method_distribution"]
        assert dist == {"AOR": 2, "AEC": 2}, "고장주입이 없는 문서는 2종 — 66.67%가 정직한 값이다"
        assert "ABV" not in dist


class TestSitsBoundaryDiagnostic:
    @pytest.mark.parametrize("subs, want", [
        ([], False),
        ([{"inputs": {"a": "1"}}], False),                                        # 한 값만
        ([{"inputs": {"a": "1"}}, {"inputs": {"a": "2"}}], False),                # 두 값 — 토글은 경계분석이 아니다
        ([{"inputs": {"a": v}} for v in ("-1", "0", "255")], True),
        ([{"inputs": {"Scenario": v}} for v in ("정상", "경계", "오류")], False),   # 입출력 없는 흐름의 대체 축
        ([{"inputs": {"a": v}} for v in ("N/A", "n/a", " ")], False),             # 값이 없는 칸
        ([{"inputs": {"a": "1", "b": "9"}}, {"inputs": {"a": "2", "b": "9"}},
          {"inputs": {"a": "3", "b": "9"}}], True),                               # 한 변수만 흔들어도 참
    ])
    def test_what_the_diagnostic_counts(self, subs, want):
        assert S._has_boundary_subcases(subs) is want

    def test_the_diagnostic_is_a_step_function_of_the_subcase_cap(self):
        """**이 사실이 라벨을 되돌린 이유 ②다.** 수치로 고정해 둔다 — 다음 사람이 다시 라벨로 쓰지 않도록.

        3 미만이면 전 흐름 0 · 3 이상이면 전 흐름 참. TC 의 성질이 아니라 설정값 하나가 정한다.
        """
        flows = [_flow(f"Fn_{i}", [f"u8V{i}"], [f"[IN] U8 u8V{i}"]) for i in range(4)]
        got = {}
        for mc in (1, 2, 3, 7):
            itcs = S.generate_itc_list([dict(f) for f in flows], max_subcases=mc)
            got[mc] = sum(1 for t in itcs if S._has_boundary_subcases(t.get("sub_cases")))
        assert got == {1: 0, 2: 0, 3: 4, 7: 4}, got

    def test_the_subcases_call_themselves_equivalence_classes(self):
        """**되돌린 이유 ③.** 같은 7값 세트를 생성기가 스스로 `EC…`(등가분할)라 이름 붙인다."""
        itcs = S.generate_itc_list([dict(_F_BV)], max_subcases=7)
        labels = [sc["case_label"] for sc in itcs[0]["sub_cases"]]
        assert any("EC1:무효-하한" in x for x in labels) and any("EC7:무효-상한" in x for x in labels), labels


class TestSitsVocabulary:
    def test_the_code_set_did_not_grow(self):
        """평가기의 방법 다양성 분모 — 라벨을 되돌렸으므로 **R76 N87 상태 그대로**여야 한다."""
        from workflow.quality import evaluator

        assert S.SITS_WRITABLE_GEN_CODES == {"AOR", "AEC", "ABV"}
        assert evaluator._SITS_GEN_METHOD_VOCAB_SIZE == float(len(S.SITS_WRITABLE_GEN_CODES)) == 3.0
        assert not hasattr(S, "_SITS_GEN_DEFAULT_BV"), "라벨 상수는 되돌렸다 — 남아 있으면 누가 다시 쓴다"

    def test_boundary_threshold_is_named_not_magic(self):
        assert S._SITS_BV_MIN_DISTINCT >= 3


# ── 게이트·공시 배선 ─────────────────────────────────────────────────────────

class TestGateAndDisclosureWiring:
    def test_the_choice_reaches_the_gate_as_a_third_option(self):
        from backend.services import docgen_requirements as req

        for doc_type in ("sts", "suts", "sits"):
            ch = req.requirements_for(doc_type)["choices"]["tc_profile"]
            vals = [o["value"] for o in ch["options"]]
            assert vals == ["", TC_PROFILE_RECOMMENDED, TC_PROFILE_EXTENDED], doc_type
            assert all(o.get("label") for o in ch["options"]), "값만 있고 설명이 없으면 고를 수 없다"

    def test_sts_disclosure_reports_both_the_enriched_and_the_untouched(self):
        """`expected_no_basis` 가 곧 "지어내지 않았다" 의 증거라 **0 이어도** 같이 싣는다."""
        from report_gen.generation_disclosures import build_disclosures

        qr = {"generation_stats": {"tc_profile": TC_PROFILE_RECOMMENDED,
                                   "expected_enriched": 177, "expected_no_basis": 73}}
        keys = {i["key"]: i["value"] for i in build_disclosures("sts", qr)}
        assert keys.get("sts_expected_enriched") == "177" and keys.get("sts_expected_no_basis") == "73"

        zero = {"generation_stats": {"tc_profile": TC_PROFILE_RECOMMENDED,
                                     "expected_enriched": 0, "expected_no_basis": 4}}
        z = {i["key"]: i["value"] for i in build_disclosures("sts", zero)}
        assert z.get("sts_expected_enriched") == "0", "보강 0 도 말한다 — 근거가 없었다는 뜻이다"

    def test_a_document_without_the_option_gets_no_such_item(self):
        """키가 없는 항목은 만들지 않는다 — 구판 산출물에 "0" 을 적으면 거짓 진술이 된다."""
        from report_gen.generation_disclosures import build_disclosures

        keys = {i["key"] for i in build_disclosures("sts", {"generation_stats": {"tc_profile": ""}})}
        assert "sts_expected_enriched" not in keys and "sts_expected_no_basis" not in keys

    def test_sits_reports_the_boundary_diagnostic_without_touching_the_label(self):
        """진단은 **0 이어도 싣는다** — 0 은 "안 흔들었다" 는 적극적 사실이다.

        그리고 note 가 Gen 칸과의 관계를 명시해야 한다: 이 수가 올라도 라벨은 안 바뀐다.
        """
        from report_gen.generation_disclosures import build_disclosures

        qr = {"total_test_cases": 120,
              "integration_flow_coverage": {"total_flows_found": 360, "flows_emitted": 120,
                                            "flows_with_boundary_subcases": 120,
                                            "boundary_subcase_min_distinct": 3}}
        item = {i["key"]: i for i in build_disclosures("sits", qr)}.get("sits_boundary_subcases")
        assert item is not None and item["value"] == "120 / 120"
        assert "3값 이상" in item["note"] and "상한" in item["note"], "상한에 좌우된다는 사실을 말해야 한다"
        assert "Gen Method 칸은 이 수와 무관" in item["note"]

        zero = copy.deepcopy(qr)
        zero["integration_flow_coverage"]["flows_with_boundary_subcases"] = 0
        z = {i["key"]: i["value"] for i in build_disclosures("sits", zero)}
        assert z.get("sits_boundary_subcases") == "0 / 120"

        old = {"total_test_cases": 120, "integration_flow_coverage": {"total_flows_found": 360}}
        assert "sits_boundary_subcases" not in {i["key"] for i in build_disclosures("sits", old)},             "구판 산출물엔 항목을 만들지 않는다(키 없으면 항목 없음)"

    def test_the_profile_row_names_the_recommended_preset(self):
        from report_gen.generation_disclosures import build_disclosures

        items = {i["key"]: i for i in build_disclosures("sts", {"generation_stats": {"tc_profile": TC_PROFILE_RECOMMENDED}})}
        row = items.get("tc_profile")
        assert row is not None and "권장" in row["value"]
        assert "시험 근거" in row["note"] and "정본 규모" in row["value"], "물량은 그대로라는 사실이 값에 보여야 한다"
