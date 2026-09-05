# tests/unit/test_sts_req_function_mapping.py
r"""STS 요구-함수 매핑 — SDS 파티션을 **함수 이름으로도** 찾는다.

## 실측 (2026-08-14, KJPDS02_PV · 정본 SDS v3.01 · 정본 SRS v3.01 · 정본 SwTS v1.02)

매핑 사슬은 `함수 → (퍼지) SDS 파티션 → 그 파티션의 related → 요구 ID` 인데, 후보가
`module_name` 파생뿐이었다. 그런데 이 프로젝트 SDS 871 파티션의 구성은:

    kind='function'  588 (전부 related 보유)   ← 키가 곧 **함수 이름**
    table_row         97 (39개만 related)      ← SDS 안의 문서 목록 행(잡음)
    design_id         72 · component 67 · design_element 34 · heading 13

즉 **588개가 함수 이름으로 열려 있는데 한 번도 그 이름으로 조회하지 않았다.**

| | 고치기 전 | 후 |
|---|---|---|
| 함수에 붙은 요구 | 43/68 | **48/68** |
| 어느 요구에도 못 붙은 함수 | 202 | **129** |
| 함수명 **정확 키**로 붙은 함수 | 0 | **356** |

변경 4개를 하나씩 켜 본 실측(요구 매핑 수):

    ①함수명 후보          43 → 48   ← 주역
    ②빈 related 에서 안 멈춤   43      (무연결 함수만 202 → 161)
    ③한글 보존 정규화        43
    ④placeholder 키 배제     43       (링크 8,046 → 7,926)

②③④ 는 요구 수를 안 올린다. 그래도 넣는 이유는 **틀린 링크를 막기 때문**이다 —
①+② 만 켜면 49 가 되는데 그 한 건(`SwTR_0606`)은 한글이 버려져 생긴 유령 매치다.
③ 을 켜면 다시 48 로 돌아온다. **숫자가 내려가는 쪽이 맞는 답이었다.**

## 못 붙은 요구는 사라지지 않는다 — 근거 없이 시험된다

`generate_test_cases` 는 매핑이 빈 요구에도 TC 를 낸다(`_generate_review_steps`).
그래서 요구 커버리지는 100% 로 보이는데 그 TC 들은 소스 근거가 0 이다. 남은 20건 중
16건은 SDS `related` **에는 있다** — 아직 그 파티션에 못 닿은 것이다. 4건
(`SwNTR_0201`·`SwNTR_0203`·`SwNTSR_0101`·`SwNTSR_0102`)은 SDS 어디에도 없다:
설계가 그 요구를 안 이은 것이므로 지어내지 않고 경고로 남긴다.
"""
from __future__ import annotations

import logging
import re

from generators.sts import map_requirements_to_functions


def _fd(name: str, module: str) -> dict:
    return {"SwUFn_001": {"id": "SwUFn_001", "name": name,
                          "module_name": module, "related": ""}}


def _part(related: str, **extra) -> dict:
    return {"related": related, "asil": "", "description": "", **extra}


class TestFunctionNameIsAMatchCandidate:
    _REQS = [{"id": "SwTR_0001"}, {"id": "SwTR_0002"}]

    def test_exact_partition_keyed_by_function_name(self):
        """모듈명은 SDS 에 없고 **함수명만** 있는 경우 — 예전엔 통째로 놓쳤다."""
        got = map_requirements_to_functions(
            self._REQS, _fd("g_SystemStatusCheck", "SysCtrl_Main"),
            sds_map={"g_systemstatuscheck": _part("SwTR_0001", kind="function")},
        )
        assert got["SwTR_0001"] == ["SwUFn_001"], "함수명 키의 파티션을 못 찾았다"

    def test_function_partition_wins_over_module_partition(self):
        """둘 다 있으면 **더 좁은 근거**(함수)를 고른다.

        모듈 파티션은 같은 모듈의 함수 전부에 같은 요구를 달아 fan-out 을 키운다.
        실측에서도 함수당 평균 요구가 8.43 → 8.16 으로 내려갔다.
        """
        got = map_requirements_to_functions(
            self._REQS, _fd("S_Motor_Init", "MotorCtrl"),
            sds_map={"motorctrl": _part("SwTR_0002"),
                     "s_motor_init": _part("SwTR_0001")},
        )
        assert got["SwTR_0001"] == ["SwUFn_001"]
        assert got["SwTR_0002"] == [], "모듈 파티션이 함수 파티션을 덮었다"

    def test_module_only_project_is_unaffected(self):
        """대조군 — SDS 에 함수 파티션이 없으면 예전과 똑같이 모듈명으로 붙는다."""
        got = map_requirements_to_functions(
            self._REQS, _fd("S_Motor_Init", "MotorCtrl"),
            sds_map={"motorctrl": _part("SwTR_0002")},
        )
        assert got["SwTR_0002"] == ["SwUFn_001"]


class TestSdsFuzzyDoesNotStopOnEmptyRelated:
    r"""`related` 가 빈 파티션에 걸렸다고 탐색을 끝내면 안 된다.

    실측 41건이 **전부 같은 칸** — `(swdsg) software architecture design
    guideline_v1.00_240229.docx`(SDS 안의 문서 목록 행) — 에서 멈췄다. 모듈 `Lin` 이
    `guide**lin**e` 에 걸린 것이다. 빈 칸은 "요구가 없다"가 아니라 **그 행이 파티션이
    아니라는** 뜻이다.
    """

    _REQS = [{"id": "SwTR_0001"}]

    # ⚠ 두 키 **어느 것도 정확 키가 아니다**. 정확 단계에서 끝나 버리면 퍼지 경로를
    #   한 줄도 안 밟는다 — 첫 판 테스트가 그래서 뮤테이션을 통째로 살려 뒀다.
    _SDS = {
        # dict 순서상 먼저 걸리는 잡음 행. `lin` ⊂ `guide**lin**e` 이고 related 는 비었다.
        "(swdsg) software architecture design guideline_v1.00.docx":
            _part("", kind="table_row"),
        "lin_uds": _part("SwTR_0001"),
    }

    def test_empty_related_row_does_not_end_the_search(self):
        got = map_requirements_to_functions(
            self._REQS, _fd("Lin_Send", "Lin"), sds_map=self._SDS)
        assert got["SwTR_0001"] == ["SwUFn_001"], "빈 칸에 걸려 탐색이 멈췄다"

    def test_the_noise_row_really_is_hit_first(self):
        """이 케이스가 **정말** 잡음 행을 먼저 만나는지 못 박는다.

        안 그러면 위 테스트가 퍼지 경로를 안 밟고도 초록이 된다(첫 판이 그랬다).
        """
        from report_gen.requirements import normalize_sds_key
        keys = list(self._SDS)
        assert "lin" in normalize_sds_key(keys[0]), "잡음 행이 `lin` 에 안 걸린다"
        assert not self._SDS[keys[0]]["related"], "잡음 행에 related 가 있으면 시나리오가 아니다"
        assert not any(k in ("lin", "lin_send") for k in self._SDS), \
            "정확 키가 있으면 퍼지 경로를 안 밟는다"

    def test_no_partition_at_all_still_yields_nothing(self):
        """대조군 — 근거가 진짜 없으면 빈 채로 둔다(지어내지 않는다)."""
        got = map_requirements_to_functions(
            self._REQS, _fd("Lin_Send", "Lin"),
            sds_map={"zzz_unrelated": _part("SwTR_0001")},
        )
        assert got["SwTR_0001"] == []


class TestNormalizationKeepsHangul:
    r"""정규화가 한글을 버리면 **틀린 링크**가 생긴다.

    `[^a-z0-9]` 로 지우면 `차속에 따른 도어 open 방지` 가 `open` **한 단어**로
    쪼그라들어 `u16s_MotorOpenCircuitRun`(모터 **단선** 검출)에 붙는다. 요구 커버리지
    숫자는 하나 오르고 내용은 틀린다 — 실측에서 실제로 그랬다(`SwTR_0606`).
    같은 식으로 `mcu 레지스터 이상감지`→`mcu`, `고장진단 및 sbcm 송신`→`sbcm`.
    """

    def test_hangul_key_does_not_collapse_to_its_english_fragment(self):
        got = map_requirements_to_functions(
            [{"id": "SwTR_0606"}], _fd("u16s_MotorOpenCircuitRun", "MotorDiag"),
            sds_map={"차속에 따른 도어 open 방지": _part("SwTR_0606")},
        )
        assert got["SwTR_0606"] == [], "한글이 버려져 'open' 유령 키가 붙었다"

    def test_hangul_key_still_matches_itself(self):
        """대조군 — 한글 파티션도 이름이 실제로 겹치면 붙는다(전면 차단이 아니다)."""
        got = map_requirements_to_functions(
            [{"id": "SwTR_0606"}], _fd("도어_열림각_송신", "DoorSend"),
            sds_map={"도어 열림각 송신": _part("SwTR_0606")},
        )
        assert got["SwTR_0606"] == ["SwUFn_001"]

    def test_placeholder_key_matches_nothing(self):
        """`n/a` → `na` 는 `sig**na**lhandler` 에도 걸린다. 실측에서 그 칸에 요구 12개."""
        got = map_requirements_to_functions(
            [{"id": "SwTR_0001"}], _fd("s_SignalHandler", "SigMod"),
            sds_map={"N/A": _part("SwTR_0001")},
        )
        assert got["SwTR_0001"] == [], "'n/a' placeholder 칸이 요구를 배포했다"


class TestUnmappedRequirementsAreReported:
    """함수에 못 붙은 요구는 **말해야 한다** — 그 TC 는 소스 근거가 0 이다."""

    def test_warns_and_names_the_unmapped_requirements(self, caplog):
        with caplog.at_level(logging.WARNING, logger="generators.sts"):
            map_requirements_to_functions(
                [{"id": "SwTR_0001"}, {"id": "SwTR_0009"}], _fd("S_Motor_Init", "MotorCtrl"),
                sds_map={"motorctrl": _part("SwTR_0001")},
            )
        warned = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("SwTR_0009" in m for m in warned), "미매핑 요구 ID 가 보고되지 않았다"
        assert not any("SwTR_0001" in m for m in warned), "붙은 요구까지 미매핑으로 보고했다"

    def test_silent_when_everything_maps(self, caplog):
        with caplog.at_level(logging.WARNING, logger="generators.sts"):
            map_requirements_to_functions(
                [{"id": "SwTR_0001"}], _fd("S_Motor_Init", "MotorCtrl"),
                sds_map={"motorctrl": _part("SwTR_0001")},
            )
        assert not [r for r in caplog.records
                    if r.levelno >= logging.WARNING and "안 붙었다" in r.getMessage()]


class TestSdsKeyNormalizationIsSingleSource:
    r"""정규화 규칙은 `report_gen.requirements` **한 곳**에만 있어야 한다.

    예전엔 `sts.py::_lookup_sds_related_ids` 와 `suts.py::_resolve_unit_asil` 이 각자
    `[^a-z0-9]` 를 들고 있었다. 이 저장소가 반복해 겪은 모양이다 — 복제를 남기면
    다음에 한쪽만 고쳐진다.
    """

    def test_neither_sds_lookup_redefines_the_ascii_only_normalizer(self):
        """SDS 맵을 읽는 **두 함수만** 겨눈다.

        ⚠ 파일 전체를 훑으면 `sts._normalize_header`(엑셀 헤더 라벨 정규화 — 도메인이
        다르고 그 템플릿 헤더는 전부 영문이다)까지 잡혀 가드가 거짓말을 한다.
        """
        from generators.sts import _lookup_sds_related_ids
        from generators.suts import _resolve_unit_asil
        from tests.unit._source_probe import source_of
        for fn in (_lookup_sds_related_ids, _resolve_unit_asil):
            # docstring 은 **뺀다** — 두 함수 다 "예전엔 `[^a-z0-9]` 였다"를 본문에
            # 적어 두었고, 그 설명 때문에 가드가 자기 자신을 잡으면 안 된다.
            src = source_of(fn).replace(fn.__doc__ or "\0", "")
            assert not re.search(r"\[\^a-z0-9\]", src), (
                f"{fn.__qualname__} 이 ASCII 전용 정규화를 다시 들고 있다 — "
                "report_gen.requirements.normalize_sds_key 를 쓸 것")
            assert "normalize_sds_key" in src, (
                f"{fn.__qualname__} 이 공용 정규화를 안 쓴다")

    def test_shared_normalizer_keeps_hangul_and_drops_punctuation(self):
        from report_gen.requirements import is_sds_placeholder_key, normalize_sds_key
        assert normalize_sds_key("차속에 따른 도어 open 방지") == "차속에따른도어open방지"
        assert normalize_sds_key("Lin_Send()") == "linsend"
        assert is_sds_placeholder_key(normalize_sds_key("N/A"))
        assert not is_sds_placeholder_key(normalize_sds_key("Nand"))

    def test_suts_asil_chain_also_skips_placeholder_keys(self):
        """SUTS 쪽에도 같은 가드가 걸렸는지 — **값으로** 확인한다.

        정규화 교체 자체는 SUTS ASIL 값을 안 바꾼다(정본 868칸 · 일치 689 · over 88 ·
        under 2 — 4개 조합 전부 동일, 라이브 경로로 A/B 재측정). 그래도 복제를 없애는
        게 목적이므로 placeholder 가드가 거기서도 사는지 못 박는다.
        """
        from generators.suts import _resolve_unit_asil
        assert _resolve_unit_asil({"module_name": "SignalHandler"},
                                  {"N/A": {"asil": "D"}}) == ("", "")
