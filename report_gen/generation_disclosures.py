"""생성 공시 — 생성기가 "무엇을 자르고·비우고·못 했는가" 를 한국어 한 줄씩으로.

## 왜 이 모듈이 생겼나

STS/SUTS/SITS 생성기는 R71~R76 에 걸쳐 절단·미상·근거 분포를 `quality_report` 에
차곡차곡 쌓았다(`boundary_tc_cut_by_req_cap`, `unknown_type_var_slots`,
`flows_dropped` …). 그런데 2026-09-20 실측으로 `frontend-v2/src` 전체에
**`quality_report` 를 읽는 곳이 0건**이었다 — 원시 JSON 사이드카를 직접 여는
사람에게만 말하는 공시는 절반만 된 공시다. 이 모듈이 그 dict 를 화면이 그대로 그릴
수 있는 목록으로 번역한다.

## 계약

- 반환은 `[{"key","label","value","note","tone"}]` — 문구·판정은 **여기가 유일한
  출처**다. 프론트는 label/value/note 를 그대로 그린다(같은 문장을 JSX 에 복제하면
  두 곳이 갈린다 — 이 저장소가 게이트 판정에서 이미 겪은 결함).
- **키가 없으면 항목을 만들지 않는다.** 0 과 부재는 다른 뜻이다: 생산자가 그 축을
  기록조차 하지 않은 구판 산출물에 "0" 을 적으면 "손실 없음" 이라는 거짓이 된다.
- 반대로 **키가 있고 값이 0 이면 대개 항목을 만든다** — "절단 0건" 은 적극적인
  사실이고, 항목이 사라지면 "구판이라 모름" 과 구분되지 않는다. 0 에서 감추는 것은
  ① 정상값이 0 인 축(모르는 프로파일 값·override 전용 unit)과 ② 다른 항목이 이미
  같은 사실을 말하는 축(안전 흐름 절단은 흐름 절단 항목이 0 을 말한다)뿐이고, 각
  자리에 이유를 주석으로 적었다.
- `tone` 은 `"info"` 또는 `"warning"` 둘뿐이다. **비운 칸은 warning 이 아니다** —
  타입을 몰라 비운 칸(`unknown_type_var_slots`)은 결함이 아니라 *지어내지 않았다*는
  뜻이라 info 로 두고, 그 뜻을 note 에 적는다. warning 은 "사람이 보고 판단해야
  손실이 복구되는 것"(상한 절단·범위 충돌·보강 실패·근거 없는 ASIL)에만 쓴다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from generators.tc_profile import (
    TC_PROFILE_EXTENDED,
    TC_PROFILE_RECOMMENDED,
    TC_PROFILE_REFERENCE,
)

__all__ = ["build_disclosures", "DISCLOSURE_TONES", "DISCLOSURE_DOC_TYPES"]

DISCLOSURE_TONES = ("info", "warning")


# ── 값 다루기 ──────────────────────────────────────────────────────────────
def _int(d: Any, key: str) -> Optional[int]:
    """`d[key]` 가 정수일 때만 그 값 — 없거나 다른 타입이면 `None`(미기록).

    `bool` 은 `int` 의 하위형이라 명시로 뺀다(`True` 가 1 로 세어지면 개수가 거짓말을 한다).
    """
    if not isinstance(d, dict):
        return None
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v


def _show(v: Optional[int]) -> str:
    """표시용 — 부재는 `—`(미기록)이지 `0`(없음)이 아니다.

    (리뷰 X7) `_int(...) or 0` 을 **표시에 쓰면** 축을 기록하지 않은 구판 산출물이 "0" 으로 보인다.
    "잘림 0" 과 "잘림 미기록" 은 화면에서 정반대 뜻이다 — 전자는 손실 없음을 단언한다.
    `or 0` 는 **감출지 말지를 정하는 자리**(0 이면 항목을 만들지 않는 축)에만 남긴다.
    """
    return "—" if v is None else str(v)


def _dist(d: Any) -> str:
    """분포 dict → `"uds_range 6430 · type 2274"`. 큰 값부터, 같으면 이름순(출력이 실행마다 흔들리지 않게)."""
    if not isinstance(d, dict) or not d:
        return ""
    items = sorted(d.items(), key=lambda kv: (-(kv[1] if isinstance(kv[1], int) else 0), str(kv[0])))
    return " · ".join(f"{k} {v}" for k, v in items)


#: note 에 이름을 몇 개까지 적나 — 전량을 쏟으면 문장이 화면을 덮는다.
_HEAD_N = 3


def _head(seq: Any) -> str:
    """목록 앞 몇 개. 잘린 사실은 호출부가 적는다."""
    if not isinstance(seq, (list, tuple)):
        return ""
    return ", ".join(str(x) for x in seq[:_HEAD_N])


def _caps(d: Any) -> str:
    """`{"max_flows": None}` → `"max_flows 상한 없음"`. `None` 은 미기록이 아니라 **상한 없음**이다(생산자 계약)."""
    if not isinstance(d, dict) or not d:
        return ""
    return " · ".join(f"{k} {'상한 없음' if v is None else v}" for k, v in sorted(d.items()))


def _item(key: str, label: str, value: Any, note: str, tone: str = "info") -> Dict[str, Any]:
    return {"key": key, "label": label, "value": str(value), "note": note, "tone": tone}


def _tone(warn: bool) -> str:
    return "warning" if warn else "info"


# ── 공통 ───────────────────────────────────────────────────────────────────
def _common_items(qr: Dict[str, Any], alt: Dict[str, Any]) -> List[Dict[str, Any]]:
    """공통 축(프로파일·상한·생성 방법).

    ⚠ **STS 는 프로파일을 `generation_stats` 안에 적고 SUTS·SITS 는 최상위에 적는다.**
      실측(2026-09-20)으로 확인한 생산자 차이라 여기서 두 자리를 다 본다 — 최상위만 보던 첫 판은
      STS 두 문서(기본·확장)에서 프로파일 줄이 통째로 사라져, 295개짜리와 2,209개짜리 문서가
      화면에서 구별되지 않았다. 생산자를 고치지 않는 이유는 `generation_stats` 를 읽는 소비처가
      이미 여럿이라서다(그쪽 정리는 별건).
    """
    out: List[Dict[str, Any]] = []
    qr = {**alt, **qr} if alt else qr      # 최상위가 이긴다 — alt 는 없을 때의 폴백일 뿐

    # 프로파일 — 이 문서가 "정본 규모" 인지 "확장" 인지. 두 문서는 나란히 놓고 보는 관계라
    # (확장 ⊇ 기본) 어느 쪽인지 모르면 TC 수를 서로 비교해 버린다.
    if "tc_profile" in qr:
        prof = str(qr.get("tc_profile") or "")
        if prof == TC_PROFILE_EXTENDED:
            label_v = "확장"
            note = ("근거 있는 시험을 상한 없이 덧붙인 문서다 — 기본(정본 규모) 문서의 시험을 "
                    "같은 ID·같은 순서로 전부 담고 그 뒤에 덧붙인다. 시험 근거 보강도 함께 켜진다.")
        elif prof == TC_PROFILE_RECOMMENDED:
            label_v = "권장(물량은 정본 규모)"
            note = ("TC 수는 기본과 같고 **시험 근거만** 올린 문서다 — 기대결과를 관측 대상이 "
                    "드러나는 문장으로 바꾸고(반환값·**쓰기** 전역), 하한 위반 경계값을 덧붙인다. "
                    "근거가 없는 자리는 바꾸지 않고 아래 '근거 없어 둔 기대결과' 로 센다. "
                    "산출이 바뀌는 것은 STS 뿐이다 — SUTS·SITS 는 이 프로파일에서 내용이 같다.")
        elif prof == TC_PROFILE_REFERENCE:
            label_v = "정본 규모(기본)"
            note = "정본과 같은 규모로만 만든 문서다 — 아래 상한에 걸린 시험은 이 문서에 없다."
        else:
            # 정규화를 거친 값이라 여기 오면 생산자 계약이 바뀐 것이다. 임의로 접지 않고 원문을 보인다.
            label_v = prof or "(미기록)"
            note = "생성기가 기록한 프로파일 값을 그대로 보인다 — 아는 값(기본/확장)이 아니다."
        out.append(_item("tc_profile", "시험 물량 프로파일", label_v, note))

    # 못 알아본 프로파일 값 — **빈 문자열이 정상**이라 0(빈 값)에서는 항목을 만들지 않는다.
    # 값이 있으면 오타 하나로 문서 규모가 바뀐 것이라 warning.
    bad = str(qr.get("tc_profile_unknown_value") or "").strip()
    if bad:
        out.append(_item(
            "tc_profile_unknown_value", "모르는 프로파일 값", bad,
            "요청에 실린 값을 알아보지 못해 기본(정본 규모)으로 만들었다 — 확장을 원했다면 다시 생성할 것.",
            tone="warning"))

    # 요청한 상한 / 실제로 건 상한. 다르면 그 사실 자체가 공시다(확장이 상한을 푼 경우가 대표).
    req, eff = qr.get("caps_requested"), qr.get("caps_effective")
    if isinstance(req, dict) or isinstance(eff, dict):
        eff_s, req_s = _caps(eff), _caps(req)
        # (리뷰 W5) **적용값이 없으면 요청값을 적용값 자리에 놓지 않는다.** 예전엔 `eff_s or req_s` 라
        #   요청만 기록한 산출물에서 요청 상한이 "실제로 건 상한" 으로 보였고, 거기에 "요청한 상한을
        #   그대로 걸었다" 는 단정까지 붙었다 — 생성기가 상한을 바꿨어도 화면은 알 수 없다.
        if not eff_s:
            value = "(적용 상한 미기록)"
            note = (f"요청 상한은 {req_s} 였지만 실제로 건 상한이 기록되지 않았다 — 요청값이 그대로 걸렸다고 "
                    f"읽지 말 것." if req_s else
                    "상한 기록이 비어 있다 — 이 문서에 어떤 상한이 걸렸는지 알 수 없다.")
            tone = "warning"
        elif req_s and eff_s != req_s:
            value, tone = eff_s, "info"
            note = "요청 상한은 " + req_s + " 였고 프로파일이 이 값으로 바꿨다 — 문서에 실제로 건 상한은 적용값이다."
        elif req_s:
            value, tone = eff_s, "info"
            note = "요청한 상한을 그대로 걸었다 — 이 상한에 걸린 시험은 문서에 없다."
        else:
            # 적용값만 있고 요청 기록이 없다 — 걸린 상한은 말할 수 있지만 "그대로" 라고는 못 한다.
            value, tone = eff_s, "info"
            note = "문서에 걸린 상한이다(요청값은 기록되지 않았다) — 이 상한에 걸린 시험은 문서에 없다."
        out.append(_item("caps", "시험 물량 상한", value, note, tone=tone))

    # 생성 방법 분포 — 세 생성기가 같은 키를 쓴다. 한 종류로 쏠려 있으면 방법 다양성이 없다는 뜻.
    if isinstance(qr.get("gen_method_distribution"), dict):
        dist = qr["gen_method_distribution"]
        out.append(_item(
            "gen_method_distribution", "생성 방법 분포", _dist(dist) or "(0건)",
            "시험을 만든 방법의 분포다(AOR 요구 기반 · ECA 동치분할 · BAA 경계값 · ABV 동작 · AEC 예외). "
            "한 방법으로 쏠리면 같은 결함 유형만 반복해 겨눈다."))
    return out


# ── STS ────────────────────────────────────────────────────────────────────
def _sts_items(qr: Dict[str, Any]) -> List[Dict[str, Any]]:
    gs = qr.get("generation_stats")
    out: List[Dict[str, Any]] = []
    if not isinstance(gs, dict):
        gs = {}

    # STS 는 공통 `caps_effective` 를 쓰지 않는다 — 상한을 `max_tc_per_req` 한 값으로 적는다(생산자 차이).
    #   이 값이 없으면 아래 "상한에 걸린 요구 50건" 이 무슨 상한인지 화면에서 알 수 없다.
    cap = _int(gs, "max_tc_per_req")
    if cap is not None:
        out.append(_item(
            "sts_max_tc_per_req", "요구당 TC 상한", str(cap),
            "한 요구 밑에 만드는 시험의 최대 개수다. 이 상한에 걸린 요구의 나머지 시험은 이 문서에 없다."))

    # 근거 보강(`recommended` 이상)이 바꾼 기대결과 수 / **근거가 없어 그대로 둔 수**.
    # 뒤 숫자가 곧 "지어내지 않았다" 의 증거라 0 이어도 싣는다 — 다만 보강을 안 켠 문서
    # (둘 다 0)에서는 항목 자체를 만들지 않는다(키 없으면 항목 없음 규약과 같은 뜻).
    _enr, _nb = _int(gs, "expected_enriched"), _int(gs, "expected_no_basis")
    if (_enr or 0) or (_nb or 0):
        out.append(_item(
            "sts_expected_enriched", "관측 대상을 적은 기대결과", str(_enr or 0),
            "무엇을 보고 합격인지 말하지 않던 문장을 관측 대상이 드러나게 바꾼 **스텝 수**다 — "
            "`기대 결과와 일치`→`반환값: (U16)` · `{함수} 정상 실행 확인`→`… 실행 후 글로벌 g_X 갱신` · "
            "`입력 경계 최솟값 설정`→`경계 최솟값 적용: n=0`. 문서에 실린 스텝만 센다(만든 수가 아니다)."))
        out.append(_item(
            "sts_expected_no_basis", "근거 없어 둔 기대결과", str(_nb or 0),
            "반환 타입도 전역도 모르는 함수라 문장을 **바꾸지 않은** 수다 — 관측 대상을 지어내지 않았다는 뜻이다."))

    # 함수 기준 커버리지 — 요구 커버리지 100% 와 **다른 축**이다. 요구는 전부 덮였는데
    # 요구당 TC 상한 때문에 매핑된 함수 1,036개 중 93개만 시험을 가진 run 이 실재한다(2026-09-20).
    with_tc, mapped = _int(gs, "functions_with_tc"), _int(gs, "mapped_functions")
    without = _int(gs, "functions_without_tc")
    # (리뷰 I7) 경고 여부가 **다른 키의 존재**에 달려 있었다 — `functions_without_tc` 를 안 적는 산출물은
    #   93/1036 이어도 info 로 나갔다. 분자·분모가 있으면 차로 유도한다(유도도 못 하면 미기록이라 말한다).
    if without is None and with_tc is not None and mapped is not None:
        without = max(0, mapped - with_tc)
    if with_tc is not None:
        value = f"{with_tc} / {mapped}" if mapped is not None else str(with_tc)
        note = ("요구에 매핑된 함수 중 실제로 시험을 가진 함수 수다. 요구 커버리지는 요구 단위 값이라 "
                "이 절단을 반영하지 않는다.")
        if without:
            note += f" 나머지 {without}개 함수는 요구당 TC 상한에 밀려 이 문서에 시험이 없다."
        elif without is None:
            note += " 시험이 없는 함수 수는 기록되지 않았다 — 0 으로 읽지 말 것."
        out.append(_item("sts_function_tc", "시험을 가진 함수", value, note, tone=_tone(bool(without))))

    # 상한에 걸린 요구 — 0 도 보인다("절단 없음" 은 적극적인 사실이고, 항목이 없으면 구판과 구별되지 않는다).
    trunc = _int(gs, "requirements_truncated_count")
    if trunc is not None:
        note = "요구당 TC 상한(max_tc_per_req)에 도달해 더 만들 수 있었는데 멈춘 요구 수다."
        if trunc:
            head = _head(gs.get("requirements_truncated"))
            note += f" 예: {head} 외 — 상한을 올리면 이 요구들의 시험이 늘어난다." if head else " 상한을 올리면 시험이 늘어난다."
        else:
            note += " 상한에 걸린 요구가 없다 — 만들 수 있는 시험을 다 담았다."
        out.append(_item("sts_requirements_truncated", "상한에 걸린 요구", f"{trunc}건", note, tone=_tone(trunc > 0)))

    # 경계값 TC 의 후보/남김/절단 — 세 수를 한 줄에 둬야 "22건 생성" 이 후보 40 중 22 라는 게 보인다.
    cand = _int(gs, "boundary_tc_candidates")
    if cand is not None:
        kept = _int(gs, "boundary_tc_kept")
        cut_req = _int(gs, "boundary_tc_cut_by_req_cap")
        cut_fn = _int(gs, "boundary_tc_cut_by_function_cap")
        # (리뷰 X7) 두 절단 축 중 **하나라도 미기록이면 합계도 미기록**이다. `or 0` 로 더하면
        #   `{"boundary_tc_candidates": 40}` 만 적은 산출물이 "잘림 0"(=손실 없음) 으로 보였다.
        cut = None if (cut_req is None or cut_fn is None) else cut_req + cut_fn
        note = ("분기 TC 뒤에 덧붙이는 경계값 시험이다. 경계값 TC 는 분기 TC 를 밀어내지 않으므로, "
                "잘린 만큼은 이 문서에 아예 없다.")
        if cut is None:
            note += " 잘린 수가 기록되지 않았다 — 0 으로 읽지 말 것."
        out.append(_item(
            "sts_boundary_tc", "경계값 TC",
            f"후보 {cand} · 남김 {_show(kept)} · 잘림 {_show(cut)}"
            + (f" (요구 상한 {_show(cut_req)} · 함수 상한 {_show(cut_fn)})" if cut else ""),
            note,
            tone=_tone(cut is None or cut > 0)))

    # 경계값을 **만들 수 없던** 함수 — 값을 지어내지 않은 결과라 결함이 아니다(info).
    unavail = _int(gs, "boundary_tc_unavailable")
    if unavail is not None:
        out.append(_item(
            "sts_boundary_unavailable", "경계값 재료 없음", f"{unavail}건",
            "입력의 값 범위를 설계서·타입 어디에서도 얻지 못해 경계값 시험을 만들지 않은 자리다. "
            "빠뜨린 게 아니라 지어내지 않은 것이다 — 설계서에 범위가 들어오면 자동으로 채워진다."))

    # 확장분 — 기본 프로파일이면 전부 0 이 정상이라 그때는 감춘다(0 을 늘어놓으면 기본 문서의 공시가 확장 이야기로 덮인다).
    ext_fn, ext_tc = _int(gs, "extended_functions") or 0, _int(gs, "extended_tcs") or 0
    if ext_fn or ext_tc:
        ext_b = _int(gs, "extended_boundary_tcs") or 0
        safety = _int(gs, "extended_functions_placed_by_safety") or 0
        out.append(_item(
            "sts_extended", "확장으로 덧붙인 시험",
            f"함수 {ext_fn} · TC {ext_tc}" + (f" (경계값 {ext_b})" if ext_b else ""),
            "기본 문서에서 시험이 하나도 없던 함수에 덧붙인 분이다."
            + (f" 그중 {safety}개는 안전 요구 밑에 놓였다." if safety else "")))
        no_detail = _int(gs, "extended_functions_without_detail")
        no_steps = _int(gs, "extended_functions_without_steps")
        if no_detail or no_steps:      # 둘 다 0/미기록이면 감춘다(항목의 존재 조건)
            out.append(_item(
                "sts_extended_thin", "확장 중 근거가 얇은 함수",
                f"상세 없음 {_show(no_detail)} · 절차 없음 {_show(no_steps)}",
                "소스에서 분기·입출력을 읽지 못해 시험 본문이 얇게 나간 함수다 — 사람이 채워야 한다.",
                tone="warning"))

    # 요구↔함수 매핑의 **근거 세기**. 정확 일치와 부분 문자열 매칭을 같은 무게로 읽으면 추적성을 과신한다.
    rfm = gs.get("requirement_function_mapping")
    if isinstance(rfm, dict):
        by = rfm.get("functions_by_path")
        if isinstance(by, dict):
            # (리뷰 X7) 세 강한 축은 **미기록이면 `—`**. `or 0` 로 적으면 `{"enrich_fuzzy": 110}` 만 있는
            #   산출물이 "자체 Related 0 · 이름 정확 0 · 정규화 0" 으로 보여 "강한 근거가 하나도 없다" 는
            #   단정이 된다 — 실제로는 그 축을 세지 않은 것뿐이다.
            own, exact, norm = (_int(by, "own_related"), _int(by, "sds_exact"), _int(by, "sds_normalized"))
            # (R77 N107) `enrich_fuzzy` = 문서 보강의 추측 매칭(프로토타입·설명의 토큰 겹침)으로만 붙은 함수 — 가장 약하다.
            #   약한 근거는 **덧셈 축**이라 일부만 기록돼도 합이 뜻을 갖는다(없는 축은 그 판이 세지 않은 것).
            #   다만 셋 다 없으면 합도 미기록이다 — 0 으로 적으면 "약한 근거 없음" 이 된다.
            weak_parts = [_int(by, k) for k in ("sds_substring", "sds_name_in_key", "enrich_fuzzy")]
            weak = None if all(p is None for p in weak_parts) else sum(p or 0 for p in weak_parts)
            bridge_only = _int(rfm, "design_id_bridge_only") or 0   # 0 이면 감춘다(항목 존재 조건)
            out.append(_item(
                "sts_mapping_basis", "요구 매핑 근거",
                f"자체 Related {_show(own)} · 이름 정확 {_show(exact)} · 정규화 {_show(norm)} · 약한 근거 {_show(weak)}"
                + (f" · 설계 ID 경유 {bridge_only}" if bridge_only else ""),
                "함수를 요구에 붙인 근거의 분포다. '약한 근거' 는 설계서 키의 부분 문자열·키 안의 이름·문서 보강의 추측 "
                "매칭으로 붙은 것이라 정확 일치와 같은 무게로 읽으면 안 된다."
                + (f" {weak}개가 여기 해당한다 — 추적성 판정 시 따로 볼 것." if weak else "")
                + ("" if weak is not None else " 약한 근거 축을 기록하지 않은 산출물이라 0 으로 읽지 말 것."),
                tone=_tone(bool(weak))))
        unlinked = _int(rfm, "unlinked")
        if unlinked is not None:
            out.append(_item(
                "sts_unlinked_functions", "요구에 못 붙은 함수", f"{unlinked}개",
                "어느 요구에도 연결되지 않은 소스 함수다 — 이 함수들은 확장 프로파일에서도 STS 에 시험이 "
                "생기지 않는다(붙일 요구가 없다)." if unlinked else
                "모든 함수가 적어도 하나의 요구에 붙었다.",
                tone=_tone(bool(unlinked))))

    # (R6/R9) 요구 원문 경계 TC — 판정이 요구 문장에서 온다. 못 쓴 사실은 사유별로 보인다(0 과 미기록을 구분).
    rb = gs.get("requirement_boundary") if isinstance(gs.get("requirement_boundary"), dict) else None
    if rb is not None and rb.get("error"):
        out.append(_item("sts_requirement_boundary", "요구 원문 경계 TC", "생성 실패",
                         f"요구 원문 경계 TC 를 만들지 못해 넣지 않았다 — {str(rb['error'])[:160]}. 나머지 STS 는 그대로다.",
                         tone="warning"))
    elif rb is not None:
        # (R51 review r2 W-D) the pass criteria and the measurement's conversion are used — by their own TCs
        skipped = {k.split(":", 1)[1]: v for k, v in rb.items() if k.startswith("skipped:") and v
                   and k not in ("skipped:acceptance_criterion", "skipped:measurement_conversion")}
        _why = {"kind_symbolic": "기호 비교(값 미상)", "kind_range": "범위", "not_an_order_comparison": "순서 비교 아님",
                "no_subject_for_value": "주어 없음", "response_constraint": "응답 제약(측정 대상)",
                "negated_condition": "부정 절", "same_subject_combination_unstated": "결합 미기재",
                "monitored_quantity_unknown": "감시량 미상", "duplicate_fact": "중복", "outcome_section": "출력·완료 조건",
                "reference_label": "기준값 라벨", "value_outside_subject_type": "변수 폭 밖의 값",
                "output_requirement": "출력 의무(…이하여야 한다)", "subject_unclear": "주어 불명확",
                "parenthesis_labels_may_share_a_quantity": "괄호 앞 이름이 같은 단위의 다른 조건과 결합(한 양일 수 있음)",
                # (R45) review reasons that are not skip reasons
                "no_subject_in_value_field": "값 칸의 주어(블록 이름 확인)", "read_as_range": "범위로 읽음(확인)",
                "deadline_or_window": "조건 절의 '이내'(기한인지 시간 창인지 확인)",
                "read_as_one_quantity": "한 양의 두 구간으로 읽음(확인)",
                # (R51 review W3) the measurement requirement and the pass criteria
                "measurement_resolution_written_otherwise": "분해능 표기 불일치(측정)",
                "measurement_tolerance_unlinked": "HW 측정 정확도 미연결(측정)",
                "measurement_path_undecided": "측정 경로 미정(측정)",
                "measurement_hw_not_given": "HW 요구사항서 미입력(측정)",
                "measurement_scale_unknown": "HW 정확도 척도 불명(측정)"}

        def _n(key):   # the producer's Counter keeps only non-zero keys: in a present block, absent is 0 (review W8)
            return _int(rb, key) or 0
        out.append(_item(
            "sts_requirement_boundary", "요구 원문 경계 TC",
            f"TC {_n('tcs')} · 스텝 {_n('steps')} · 사실 {_n('facts_used')} / {_n('facts')}",
            "요구 문장이 직접 적은 임계·유지시간마다 경계 3점(적힌 정밀도 한 단위)을 두고, 판정은 그 문장의 조건 결합대로 "
            "요구 원문에서 낸다(코드가 아니라 요구 기준 — 조건 밖의 점은 '그 문장의 동작 대상 아님'). 근거 문장은 "
            "'Requirement Evidence' 시트에 있다."
            + (" 못 쓴 사실: " + ", ".join(f"{_why.get(k, k)} {v}" for k, v in sorted(skipped.items())) + "."
               if skipped else "")
            + (f" 변수 폭 밖이라 뺀 경계 점 {_n('points_outside_subject_type')}." if _n("points_outside_subject_type")
               else "")
            + (f" 'Requirement Evidence' 시트를 쓰지 못했다 — {str(rb['evidence_sheet_error'])[:160]}."
               if rb.get("evidence_sheet_error") else ""),
            tone=_tone(bool(rb.get("evidence_sheet_error")))))
        out.extend(_traced_system_items(rb, _why))
        out.extend(_hw_tolerance_items(rb))
        out.extend(_measurement_items(rb))
        out.extend(_ai_review_items(rb))
        out.extend(_ai_path_items(rb))
        out.extend(_inclusion_conflict_items(rb))
        out.extend(_value_difference_items(rb))
        out.extend(_requirement_review_items(rb, _why))
    return out + _sts_tail_items(qr)


def _requirement_review_items(rb: Dict[str, Any], why_text: Dict[str, str]) -> List[Dict[str, Any]]:
    """(R45) 요구 문서가 정하지 않아 경계 TC 로 만들지 못한 조건 — 채울 근거가 없어도 항목으로 보인다(사용자 방향
    2026-09-30 "잘못되거나 충돌되는 것은 문서나 웹에 표시"). R45 이전 산출물엔 키가 없어 항목을 만들지 않는다(없음 ≠ 0)."""
    n = _int(rb, "review_item_count")
    if n is None:
        return []
    if not n:
        return [_item("sts_requirement_review", "요구 원문 검토 항목", "0건",
                      "경계 TC 로 만들지 못한 조건 중 사람이 정해 채울 것(주어 없음·결합 미기재·범위의 경계 포함 등)이 없다.")]
    by = rb.get("review_by_reason") if isinstance(rb.get("review_by_reason"), dict) else {}
    items = [i for i in (rb.get("review_items") or []) if isinstance(i, dict)]

    def _who(i):
        ids = [str(x) for x in (i.get("srs_ids") or [])]
        return ids[0] + (f" 외 {len(ids) - 1}" if len(ids) > 1 else "") if ids else "—"
    shown = [f"{_who(i)} {i.get('source')}: `{str(i.get('fact') or '')[:40]}` — {why_text.get(str(i.get('reason')), i.get('reason'))}"
             for i in items[:5]]
    read_n = _int(rb, "review_read_count") or 0
    # (R45 review W5) the sheet may have failed on its own: then it is not "written there"
    sheet_err = str(rb.get("review_sheet_error") or "")
    where = (f"'Requirement Review' 시트를 쓰지 못했다 — {sheet_err[:160]} (항목은 품질 리포트 `review_items` 에만 있다)"
             if sheet_err else
             "값을 지어내지 않고 원문·사유·정할 것을 STS 의 'Requirement Review' 시트에 전부 적었다"
             # (R45 review I7) the conflicts are compared only when system documents were read
             + ("(요구 문서 경계 포함 불일치" + (" · 값 차이" if "value_differences" in rb else "") + " 후보도 같은 시트)"
                if "inclusion_conflicts" in rb else ""))
    return [_item(
        "sts_requirement_review", "요구 원문 검토 항목",
        f"{n}건" + (f" · 그중 읽은 결합 {read_n}" if read_n else "") + _evidence_value(rb),
        ", ".join(f"{why_text.get(k, k)} {v}" for k, v in by.items()) + ". "
        + " / ".join(shown)
        + (f" 외 {n - len(shown)}건(품질 리포트 `review_items` 에 {len(items)}건까지)." if n > len(shown) else ".")
        + " — 요구 문서가 정하지 않아 경계 TC 로 만들지 못한 조건과, 원문에 적혀 있지 않은 결합을 생성기가 읽어 스텝한 곳"
          "('읽은 결합 — 확인')이다. " + where + ". 한 블록을 여러 요구가 인용하면 한 행에 요구를 모두 적는다."
        + _evidence_note(rb),
        tone="warning")]


def _evidence_value(rb: Dict[str, Any]) -> str:
    """(R46) 근거 후보를 찾은 항목 수 — R46 이전 산출물엔 키가 없어 붙이지 않는다(없음 ≠ 0). 찾을 항목이 0 이면 "0/0" 대신
    아무것도 붙이지 않는다(리뷰 I3 — 탐색하지 않은 것을 탐색한 것처럼 적지 않는다)."""
    searched = _int(rb, "review_evidence_searched")
    if not searched:
        return ""
    return f" · 다른 문장에 근거 후보 {_int(rb, 'review_evidence_found') or 0}/{searched}"


_FILL_CHECK_TEXT = (("verified", "이 문장에 넣어 확인"), ("needs_more", "더 풀 것이 남음"), ("rewrite", "다시 쓰기 예시"),
                    ("not_applicable", "해당 없음(측정 요구 · 판정 기준)"), ("unchecked", "안내 실패"))


def _evidence_note(rb: Dict[str, Any]) -> str:
    """(R46) 사용자 방향 2026-09-30 "부족한 것은 찾아보고, 그래도 없으면 표시하고 채우면 개선된다고 안내" — 어느 문서를
    찾았는지, 'If Filled' 를 어떻게 확인했는지, 무엇을 적으면 무엇이 생기는지. 검토 목록은 끝 120 자를 남기므로 안내를
    끝에 둔다(리뷰 I13 — 끝 문장이 120 자 안에서 온전하도록)."""
    if "review_evidence_searched" not in rb and "review_evidence_error" not in rb:
        return ""
    parts = []
    checks = rb.get("review_fill_checks") if isinstance(rb.get("review_fill_checks"), dict) else {}
    shown = [f"{label} {checks[k]}" for k, label in _FILL_CHECK_TEXT if checks.get(k)]
    if shown:
        parts.append("'If Filled'(원문에 무엇을 적으면 스텝이 생기는지): " + " · ".join(shown) + ".")
    err = str(rb.get("review_evidence_error") or "")
    searched = _int(rb, "review_evidence_searched") or 0
    found = _int(rb, "review_evidence_found") or 0
    if err:
        parts.append(f"근거 후보 탐색은 실패했다 — {err[:120]}.")
    elif not searched:
        # (R51 review r5 I-2) a measured criterion has a unit but is no gap — not "no item with a unit"
        parts.append("근거 후보: 다른 문장에서 찾을 보류 항목이 없어 찾지 않았다(측정 요구 · 판정 기준 항목은 탐색 대상 아님)."
                     if checks.get("not_applicable") else "근거 후보: 단위 있는 값의 보류 항목이 없어 찾지 않았다.")
    else:
        related = _int(rb, "review_evidence_related") or 0
        docs = "·".join(str(d) for d in (rb.get("review_evidence_documents") or []))
        parts.append(f"근거 후보: 단위 있는 값 {searched}건 중 {found}건은 준 문서({docs})의 다른 문장이 같은 값·단위를 스텝할 수 "
                     f"있게 적었다(그중 같은 요구·인용 블록 {related}건 — 옮길 문장의 예일 뿐, 같은 양인지 확인할 것. 생성기는 "
                     f"쓰지 않는다). 후보 없는 {searched - found}건은 적을 말부터 요구 문서에서 정해야 한다.")
    parts.append("채우면: 'If Filled' 칸대로 요구 문서에 적고 다시 생성하면 그 값의 경계 스텝이 생긴다(더 풀 것이 남은 항목은 "
                 "그것까지" + ("; 측정 요구 · 판정 기준 항목은 경계 스텝이 아니라 측정으로 확인" if checks.get("not_applicable") else "")
                 + ").")
    return " " + " ".join(parts)

_DIFF_TIER_TEXT = {"same_subject": "같은 주어", "same_condition": "같은 조건의 유지시간", "within_step": "한 눈금 안",
                   "only_pair": "유일한 짝"}


def _value_difference_items(rb: Dict[str, Any]) -> List[Dict[str, Any]]:
    """(R48) 요구 문서 값 차이 후보 — SRS 가 적은 조건 값을 인용 블록이 적지 않고, 인용 블록이 같은 단위·같은 쪽(하한/상한)에
    **다른 값**을 적은 곳 중 한 임계로 볼 근거(5% 안에서 같은 주어 · 한 눈금 안 · 그 단위·쪽의 유일한 짝, 유지시간은 같은
    조건의 유지시간)가 있는 것. 시스템 문서를 읽은
    생성에만 있다(키가 없으면 항목 없음 — R48 이전 산출물). 비교할 인용 블록이 없었으면 0 이 아니라 '—'."""
    n = _int(rb, "value_differences")
    if n is None:
        return []
    compared = _int(rb, "inclusion_blocks_compared")
    errors = [str(e) for e in (rb.get("value_difference_errors") or [])]
    n_err = _int(rb, "value_difference_error_count") or len(errors)
    err_note = (f" 비교 중 오류로 건너뛴 요구 {n_err}개(예: {errors[0][:80]})." if errors else "")
    if compared == 0:
        return [_item("sts_requirement_value_differences", "요구 문서 값 차이", "—",
                      "요구가 인용한 시스템 블록 중 읽은 문서에 있는 것이 없어 비교하지 못했다(0 건이 아니라 미측정)." + err_note,
                      tone=_tone(bool(errors)))]
    if not n:
        return [_item("sts_requirement_value_differences", "요구 문서 값 차이", "0건" + (f" · 오류 {n_err}" if errors else ""),
                      "SRS 조건 값과 그 요구가 Related ID 로 인용한 SyRS·SyDS 블록의 같은 단위·같은 쪽 조건 값이 한 임계로 볼 "
                      "근거(5% 안에서 같은 주어 · 한 눈금 안 · 유일한 짝, 또는 같은 조건의 유지시간)가 있으면서 다르게 적힌 곳을 "
                      "찾지 못했다(결과 칸·출력 의무·검증 기준·요소 입력 칸·범위(~)·단위 없는 값은 비교하지 않는다)." + err_note,
                      tone=_tone(bool(errors)))]
    items = [i for i in (rb.get("value_difference_items") or []) if isinstance(i, dict)]

    def _st(x):
        ref = f" (기준 {x.get('reference')})" if x.get("reference") else ""
        return f"`{x.get('subject')} {x.get('text')}{ref}`"

    def _one(i):
        others = [o for o in (i.get("others") or []) if isinstance(o, dict)]
        first = others[0] if others else {}
        tiers = "·".join(_DIFF_TIER_TEXT.get(str(t), str(t)) for t in (first.get("tiers") or []))
        more = int(i.get("other_count") or len(others)) - 1
        return (f"{i.get('srs_id')}: SRS {_st(i.get('srs') or {})} ↔ {first.get('source')} {_st(first)} [{tiers}]"
                + (f" 외 {more}" if more > 0 else ""))
    shown = [_one(i) for i in items[:5]]
    reqs = _int(rb, "value_difference_requirements")
    by = rb.get("value_difference_by_tier") if isinstance(rb.get("value_difference_by_tier"), dict) else {}
    # (review W5) the sheet may have failed on its own: then the items are not "there"
    sheet_err = str(rb.get("review_sheet_error") or "")
    where = (f"'Requirement Review' 시트를 쓰지 못했다 — {sheet_err[:120]} (항목은 품질 리포트 `value_difference_items` 에만 "
             "있다)." if sheet_err else "전부 STS 'Requirement Review' 시트에 있다.")
    return [_item(
        "sts_requirement_value_differences", "요구 문서 값 차이 후보",
        f"{n}건" + (f" (요구 {reqs})" if reqs is not None else "") + (f" · 오류 {n_err}" if errors else ""),
        " / ".join(shown)
        + (f" 외 {n - len(shown)}건(품질 리포트 `value_difference_items` 에 {len(items)}건까지)." if n > len(shown) else ".")
        + err_note
        + " — SRS 가 적은 조건 값을 그 요구가 Related ID 로 인용한 SyRS·SyDS 블록은 적지 않고, 같은 단위·같은 쪽(하한끼리 · "
          "상한끼리)에 다른 값을 적은 곳이다. 한 임계로 볼 근거가 있는 쌍만 짝지었다(한 후보가 여러 근거일 수 있음): "
        + ", ".join(f"{_DIFF_TIER_TEXT.get(k, k)} {v}" for k, v in by.items())
        + "(두 값이 5% 안에서 — 같은 주어 · 한 눈금 안(성긴 쪽 표기) · 그 요구와 인용 블록이 그 단위·쪽에 값을 하나씩만 적음; "
          "유지시간은 값이 멀어도 두 문장이 같은 조건을 유지할 때 — SRS 가 더 길면 시스템 요구 시간 안에 판정하지 못할 수 "
          "있다). 반대쪽(진입 미만 ↔ 해제 이상)은 짝짓지 않지만 같은 쪽의 두 단계 임계(경고·고장)는 짝지어질 수 있다. 어느 값이 "
          "맞는지는 생성기가 정하지 않는다(경계 TC 는 각 문장대로 판정) — 같은 임계인지부터 확인하고, 같으면 문서 검토로 한 "
          "값에 맞추고 다른 임계면 결함 아님으로 닫는다. " + where,
        tone="warning")]


_CONFLICT_TAG = {"outcome": " [결과]", "stimulus": " [시험 입력]"}


def _inclusion_conflict_items(rb: Dict[str, Any]) -> List[Dict[str, Any]]:
    """(R33) 요구 문서 간 경계 포함 불일치 후보 — 시스템 문서를 읽은 생성에만 있다(없음과 0 을 구분: 키가 없으면 항목 없음).
    비교할 인용 블록이 하나도 없었으면 0 이 아니라 '—'(review W4). 검토 목록은 앞 230 자·끝 120 자를 남기므로 쌍과 오류
    수를 설명보다 앞에 둔다."""
    n = _int(rb, "inclusion_conflicts")
    if n is None:
        return []
    compared = _int(rb, "inclusion_blocks_compared")
    errors = [str(e) for e in (rb.get("inclusion_conflict_errors") or [])]
    n_err = _int(rb, "inclusion_conflict_error_count") or len(errors)
    err_note = (f" 비교 중 오류로 건너뛴 요구 {n_err}개(예: {errors[0][:80]})." if errors else "")
    # (R43 review W1) an output from before R43 never looked within one source: it keeps the R33 wording
    has_within = "inclusion_conflicts_within_source" in rb
    if compared == 0 and not n:
        return [_item("sts_requirement_inclusion_conflicts", "요구 문서 경계 포함 불일치", "—",
                      "요구가 인용한 시스템 블록 중 읽은 문서에 있는 것이 없어 비교하지 못했다(0 건이 아니라 미측정)."
                      + err_note, tone=_tone(bool(errors)))]
    if compared == 0:
        # (R43 review C1) no cited block to compare with, yet one source's own lines disagree: the candidates are shown,
        #   and only the comparison across documents is said to be unmeasured
        scope = "블록 0 곳(문서 간 비교는 미측정 — 앞의 쌍은 전부 한 출처 안)"
    else:
        scope = f"블록 {compared} 곳(요구 × 블록)" if compared is not None else "블록"
    if not n:
        where = (f"SRS 와 그 요구가 Related ID 로 인용한 {scope}에서, 그리고 한 출처(SRS 원문 또는 한 블록)의 두 줄 "
                 "사이에서" if has_within else
                 f"SRS 와 그 요구가 Related ID 로 인용한 {scope}에서")
        return [_item("sts_requirement_inclusion_conflicts", "요구 문서 경계 포함 불일치",
                      "0건" + (f" · 오류 {n_err}" if errors else ""),
                      where + " 같은 값·같은 단위를 경계 포함만 다르게 적은 쌍을 찾지 못했다"
                      + ("." if has_within else "(한 출처 — SRS 원문 또는 한 블록 — 안의 쌍은 보지 않는다).") + err_note,
                      tone=_tone(bool(errors)))]
    items = [i for i in (rb.get("inclusion_conflict_items") or []) if isinstance(i, dict)]

    def _side(x):
        ref = f" (기준 {x.get('reference')})" if x.get("reference") else ""
        return f"{x.get('source')} `{x.get('subject')} {x.get('text')}{ref}`"

    def _flag(i):
        # (R43) two lines of one source: they may be two conditions or two actions on purpose — read both first
        within = " (한 출처 안의 두 줄 — 다른 조건·다른 동작일 수 있으니 원문 확인)" if i.get("within_source") else ""
        if i.get("same_subject"):
            return within
        return within + (" (한쪽 주어 없음 — 원문으로 같은 조건인지 확인)" if i.get("subject_missing") else
                         " (주어 이름이 다름 — 같은 신호인지 먼저 확인)")
    shown = [f"{i.get('srs_id')}{_CONFLICT_TAG.get(str(i.get('role')), '')}: {_side(i.get('a') or {})} ↔ "
             f"{_side(i.get('b') or {})}{_flag(i)}" for i in items[:5]]
    reqs, vals = _int(rb, "inclusion_conflict_requirements"), _int(rb, "inclusion_conflict_values")
    within_n = _int(rb, "inclusion_conflicts_within_source")
    return [_item(
        "sts_requirement_inclusion_conflicts", "요구 문서 경계 포함 불일치 후보",
        f"{n}건" + (f" (요구 {reqs} · 값 {vals})" if reqs is not None and vals is not None else "")
        + (f" · 그중 한 출처 안 {within_n}" if within_n else "")
        + (f" · 오류 {n_err}" if errors else ""),
        " / ".join(shown)
        + (f" 외 {n - len(shown)}건(품질 리포트 `inclusion_conflict_items` 에 {len(items)}건까지)." if n > len(shown) else ".")
        + err_note
        + " — SRS 와 그 요구가 Related ID 로 인용한 SyRS·SyDS 블록(또는 두 블록)"
        + (", 그리고 한 출처(SRS 원문 또는 한 블록)의 서로 다른 두 줄" if has_within else "")
        + "이 같은 값·같은 단위를 경계 포함만 달리 적은 곳이다(이상 ↔ 초과, 이하 ↔ 미만): 조건끼리는 그 값이 한 문장의 "
          "조건에는 들고 다른 문장의 조건에는 들지 않는다, [결과] 는 결과 기준끼리, [시험 입력] 은 검증 기준(시험 기술)의 입력이 "
          "요구 조건이 제외한 값을 포함한다(그 값에서 반응을 기대하는 긍정 시험이면 요구가 반응하지 않는 입력에서 반응을 "
          "기대한다 — 부정 시험이면 판정은 갈리지 않으니 원문으로 확인; 시험 입력이 더 엄격한 쪽은 후보가 아니다). 어느 쪽이 "
          "맞는지는 생성기가 정하지 않는다(경계 TC 는 각 문장대로 판정) — 문서 검토로 정할 결함 후보다. 값과 단위로만 "
          f"짝지었으니 주어 표시를 먼저 볼 것. 범위: 인용 {scope}"
        + (", 그리고 한 출처(SRS 원문 또는 한 블록)의 서로 다른 두 줄(표시 '한 출처 안' — 한 문서가 의도로 두 조건·두 동작을 "
           "달리 적었을 수 있다)." if has_within else ", 한 출처(SRS 원문 또는 한 블록) 안의 쌍은 보지 않는다."),
        tone="warning")]


def _ai_path_items(rb: Dict[str, Any]) -> List[Dict[str, Any]]:
    """(R54) AI 제안 감시 경로 — 문서가 정하지 않은(허브) 경계의 HW 감시 블록을 LLM 이 후보 중에서 고르고 그 블록 원문으로
    무엇을 감시하는지 인용한 것. 확인한 것은 '그 블록 원문에 있고 경계 주어의 이름이 그 블록에만 맞으며 값이 그 척도 위' 까지 —
    경로는 정하지 않는다(사람이 확인해 HW 문서나 SRS Related ID 에 적으면 그때)."""
    ai = rb.get("ai_path")
    if not isinstance(ai, dict):
        return []
    if ai.get("error"):
        return [_item("sts_ai_path", "AI 제안(감시 경로)", "실패",
                      f"감시 경로 AI 제안을 만들지 못했다 — {str(ai['error'])[:160]}. 경계 TC 는 그대로다.", tone="warning")]
    eligible = int(ai.get("eligible") or 0)
    if not eligible:
        return []
    failed, cache_error = int(ai.get("call_failed") or 0), str(ai.get("cache_error") or "")
    how = (f"모델 {ai.get('model')}, 새로 물은 {ai.get('asked', 0)} 개, {ai.get('elapsed_s', 0)} 초" if ai.get("called")
           else "이번 생성은 AI 를 부르지 않음 — 캐시만 읽음")
    note = (f"감시 경로가 정해지지 않은 경계 {eligible} 개(서로 다른 경계 {ai.get('distinct', 0)} 개) 중 AI 가 후보 HW 블록의 원문으로 "
            f"경계 주어를 그 블록에만 묶은 것 {ai.get('verified', 0)} 개, 검증에서 버린 것 {ai.get('rejected', 0)} 개, 원문으로 정하지 "
            f"못함 {ai.get('unknown', 0)} 개"
            + (f", 묻지 않음 {ai.get('not_asked')} 개" if ai.get("not_asked") else "")
            + (f", 호출 실패 · 응답 해석 실패 {failed} 개(캐시하지 않음 — 다음 생성에서 다시 묻는다)" if failed else "")
            + f"({how}, 캐시 {ai.get('cached', 0)})."
            + (f" {cache_error[:120]} — 이번 답은 다음 생성에 남지 않는다." if cache_error else "")
            + " 'Requirement Evidence' 시트의 'AI Path Proposal (Checked)' 열 — 확인한 것은 인용이 그 블록 원문에 있고 경계 주어의 "
            "이름이 인용 · 그 블록 이름과 맞으며 다른 후보 블록과는 안 맞는다는 것, 절대 허용오차면 값이 그 척도 위라는 것까지다"
            "(상대 허용오차는 척도를 확인하지 않는다 — 칸에 적음). 경로는 정하지 않는다: 맞으면 HW 요구사항서나 SRS 의 Related ID "
            "에 적고 다시 생성하면 경로가 정해진다.")
    return [_item("sts_ai_path", "AI 제안(감시 경로)", f"인용 확인 {ai.get('verified', 0)} / {eligible}", note,
                  tone=_tone(failed > 0 or bool(cache_error)))]


def _ai_review_items(rb: Dict[str, Any]) -> List[Dict[str, Any]]:
    """(R52) AI 제안 — 검토 항목의 빠진 주어를 LLM 이 실제 이름 중에서 고르고 그 이름과 값을 함께 적은 원문 인용을 댄 것.
    확인한 것은 '이름이 실재하고 인용이 원문에 있다' 까지 — 대응은 사람이 확인한다(스텝·판정에 쓰지 않음). 키가 없으면 대상
    항목이 없거나 R52 이전 산출물."""
    ai = rb.get("ai_review")
    if not isinstance(ai, dict):
        return []
    if ai.get("error"):
        return [_item("sts_ai_review", "AI 제안(검토 항목 주어)", "실패",
                      f"AI 제안을 만들지 못했다 — {str(ai['error'])[:160]}. 검토 항목과 TC 는 그대로다.", tone="warning")]
    eligible = int(ai.get("eligible") or 0)
    if not eligible:
        return []
    by_quote, by_block = int(ai.get("verified_by_quote") or 0), int(ai.get("verified_by_block_name") or 0)
    by_words = int(ai.get("verified_by_words") or 0)
    failed, cache_error = int(ai.get("call_failed") or 0), str(ai.get("cache_error") or "")
    # (review W7) a generation path that calls no AI is no "AI 설정 없음" (the Jenkins STS handler never passes one)
    how = (f"모델 {ai.get('model')}, 새로 물은 {ai.get('asked', 0)} 개, {ai.get('elapsed_s', 0)} 초" if ai.get("called")
           else "이번 생성은 AI 를 부르지 않음 — 캐시만 읽음")
    note = (f"주어가 없는 검토 항목 {eligible} 개 중 AI 가 원문으로 이름과 값을 함께 적은 곳을 댄 것 {by_quote} 개"
            + (f"(이름 그대로는 아니고 이름의 단어를 모두 적은 것 {by_words} 개 따로)" if by_words else "")
            + f", 값만 적는 칸의 블록 이름 {by_block} 개, 검증에서 버린 것 {ai.get('rejected', 0)} 개, 원문으로 정하지 못함 {ai.get('unknown', 0)} 개"
            + (f", 묻지 않음 {ai.get('not_asked')} 개" if ai.get("not_asked") else "")
            + (f", 호출 실패 · 응답 해석 실패 {failed} 개(캐시하지 않음 — 다음 생성에서 다시 묻는다)" if failed else "")
            + f"({how}, 캐시 {ai.get('cached', 0)})."
            + (f" 후보 이름이 상한에서 잘린 항목 {ai['candidates_cut']} 개." if ai.get("candidates_cut") else "")
            + (f" {cache_error[:120]} — 이번 답은 다음 생성에 남지 않는다." if cache_error else "")
            + " 'Requirement Review' 시트의 'AI Proposal (Checked)' 열 — 확인한 것은 이름이 실재하고 인용이 원문에 있으며 다른 "
            "후보를 가리키지 않는다는 것까지다(후보로 뽑히지 않는 이름 — 밑줄 없는 `EN1` 같은 — 은 보지 못한다). 대응은 사람이 "
            "확인하고, 스텝·판정에는 쓰지 않는다.")
    return [_item("sts_ai_review", "AI 제안(검토 항목 주어)",
                  f"인용 확인 {by_quote}" + (f" · 단어 {by_words}" if by_words else "") + f" · 블록 이름 {by_block} / {eligible}", note,
                  tone=_tone(failed > 0 or bool(cache_error)))]


def _measurement_items(rb: Dict[str, Any]) -> List[Dict[str, Any]]:
    """(R51) 측정 요구 TC — 요구가 나열한 입력 값마다 출력이 보고할 값·코드와 판정 범위(HW 측정 정확도 + 분해능 한 칸) —
    와 판정 기준 TC(비기능 요구의 검증 기준이 적은 상·하한: 측정해 확인, 입력으로 설정하지 않음 — 경계 점 없음). 키가
    없으면 해당 요구가 없거나 R51 이전 산출물이라 항목 없음. HW 정확도가 이어지지 않은 판정 범위는 분해능만이라 실측(HIL)이
    벗어날 수 있다 — 그 사실과 채우면 생기는 것을 적는다."""
    tcs = _int(rb, "measurement_tcs") or 0
    accept = _int(rb, "acceptance_tcs") or 0
    if not tcs and not accept:
        return []
    linked = _int(rb, "measurement_hw_linked") or 0
    undecided = _int(rb, "measurement_path_undecided") or 0
    not_given = _int(rb, "measurement_hw_not_given") or 0          # (review W4)
    scale_unknown = _int(rb, "measurement_scale_unknown") or 0     # (review W6)
    unlinked = tcs - linked
    parts = []
    if tcs:
        parts.append(f"요구가 입력 값을 나열하고 출력의 변환식(코드 범위 · offset · 분해능)을 적은 측정 요구 {tcs} 개를 입력 값마다 "
                     "기대 코드와 판정 범위로 스텝했다(분해능은 범위와 코드 폭으로 계산 — 표기가 다르면 'Requirement Review' "
                     "시트에 적음, 반올림 방식은 미기재라 한 칸을 더함).")
        if linked:
            parts.append(f"그중 {linked} 개는 Related ID 로 이어진 HW 블록의 측정 정확도를 판정 범위에 넣었다"
                         + (f"(감시 경로 미정 {undecided} — 가장 큰 값)" if undecided else "") + ".")
    if accept:
        parts.append(f"비기능 요구의 검증 기준이 적은 상·하한 {_int(rb, 'acceptance_criteria') or 0} 개(CPU 부하 · 메모리 "
                     f"점유율 등)는 판정 기준 TC {accept} 개의 '측정' 스텝으로 적었다 — 측정해 확인하는 값이라 입력으로 설정하는 "
                     "경계 점을 만들지 않는다(변이 판별을 주장하지 않음).")
    if not_given:
        parts.append(f"측정 요구 {not_given} 개는 HW 요구사항서를 주지 않아 판정 범위가 분해능뿐이다 — 실측(HIL)이 벗어날 수 "
                     "있다: HW 요구사항서(HwRS·HRS)를 주면 그 입력을 감시하는 HW 블록의 허용 오차가 들어간다.")
    if scale_unknown:
        parts.append(f"측정 요구 {scale_unknown} 개는 이어진 HW 블록의 허용오차가 감시 노드 척도라 분해능뿐이다 — 그 분압비를 "
                     "HW 설계서에 적으면 환산해 넣는다.")
    if unlinked - not_given - scale_unknown > 0:
        parts.append(f"측정 요구 {unlinked - not_given - scale_unknown} 개는 이어진 HW 측정 정확도가 없어 판정 범위가 "
                     "분해능뿐이다 — 실측(HIL)이 벗어날 수 있다: 그 입력을 감시하는 HW 블록이 인용하는 시스템 ID 를 요구의 "
                     "Related ID 에 적으면 판정 범위에 들어간다.")
    conversion = _int(rb, "skipped:measurement_conversion") or 0
    if conversion:
        parts.append(f"측정 요구의 변환식에서 읽힌 값 {conversion} 개(코드 범위 · 변환 범위)는 측정 TC 가 썼다 — 경계 TC 의 "
                     "'못 쓴 사실' 에 넣지 않는다.")
    value = " · ".join(([f"측정 TC {tcs} · 스텝 {_int(rb, 'measurement_steps') or 0}"] if tcs else [])
                       + ([f"판정 기준 TC {accept}"] if accept else []))
    return [_item("sts_measurement", "측정 요구 · 판정 기준 TC", value, " ".join(parts), tone=_tone(unlinked > 0))]


def _hw_tolerance_items(rb: Dict[str, Any]) -> List[Dict[str, Any]]:
    """(R49) HW 측정 허용오차 — HW 요구사항서를 준 생성엔 연결된 경계 사실 수와 그중 한 눈금이 허용오차 안인 수, 안 줬으면
    '미입력' 과 주면 무엇이 생기는지(사용자 방향 2026-09-30 "없으면 표시하고 채우면 개선된다고 안내"). 키가 없으면 R49 이전
    산출물이라 항목 없음(없음 ≠ 미입력)."""
    doc = rb.get("hw_document")
    if not isinstance(doc, dict):
        return []
    if doc.get("given") is False:
        unused = _design_unused_note(rb, "없어")
        return [_item("sts_hw_tolerance", "HW 측정 허용오차", "미입력",
                      "HW 요구사항서(HwRS·HRS)를 주지 않아 경계 TC 의 HW 측정 허용오차를 보지 않았다." + unused + " 주면 SRS 가 "
                      "인용한 시스템 블록을 같이 인용하는 HW 블록의 '허용 오차'(예: 배터리 전압 감시 ±3%)를 경계 TC 옆에 적고, "
                      "경계 점 간격이 그 안이라 HIL 에서 이상/초과를 가를 수 없는 TC 에는 판정 방법(SW 변수 직접 주입 · 허용오차 "
                      "밖 점)을 사전조건에 적는다.")]
    if doc.get("error"):
        return [_item("sts_hw_tolerance", "HW 측정 허용오차", "읽기 실패",
                      f"HW 요구사항서를 읽지 못해 경계 TC 는 허용오차 없이 만들었다 — {str(doc.get('error'))[:160]}"
                      + (f" ({doc.get('file')})" if doc.get("file") else "") + "."
                      + _design_unused_note(rb, "읽지 못해"), tone="warning")]
    source = (f"({doc.get('file') or ''} — HW 블록 {doc.get('blocks')} 중 '허용 오차' 를 적은 것 "
              f"{doc.get('blocks_with_tolerance')})")
    if not doc.get("blocks"):
        # (R49 review W3) read but no HW requirement table: another document (or another layout), not "none linked"
        return [_item("sts_hw_tolerance", "HW 측정 허용오차", "HW 요구 표 없음",
                      "HW 요구사항서에서 HW 요구 표(ID `Hw…`)를 하나도 찾지 못했다 — 다른 문서를 등록했거나 양식이 다르다 "
                      + source + ".", tone="warning")]
    groups = _int(rb, "hw_tolerance_groups") or 0
    inside = _int(rb, "hw_tolerance_inside_step") or 0
    undecided = _int(rb, "hw_tolerance_path_undecided") or 0
    unknown = _int(rb, "hw_tolerance_scale_unknown") or 0
    if not groups:
        return [_item("sts_hw_tolerance", "HW 측정 허용오차", "0",
                      "경계 TC 의 요구가 인용한 시스템 블록을 같이 인용하는(Related ID) HW 블록의 허용오차가 그 값의 단위로 "
                      "이어지는 곳이 없었다 " + source + ".")]
    # (R49 review I3) what to do first — the gate board keeps the first 230 and the last 120 characters
    return [_item(
        # (R50 review r2 I4) the value is never clipped on the board: what a reader must settle is counted there
        # (r3 W1) one count per boundary — a boundary refused and not scaled is one to settle, not two
        "sts_hw_tolerance", "HW 측정 허용오차", f"경계 사실 {groups} · 한 눈금이 허용오차 안 {inside}" + (
            f" · 문서 확인 {settle}" if (settle := _int(rb, "hw_tolerance_to_settle") or 0) else ""),
        f"한 눈금이 HW 측정 허용오차 안인 경계 {inside} 개는 HIL 에서 경계 포함(이상/초과·이하/미만)을 가를 수 없다 — 그 TC 의 "
        "사전조건에 판정 방법을 적었다: SW 변수 직접 주입(SIL·디버거)으로 판정하거나, 허용오차 밖 점(값 ± (가장 큰 후보 "
        f"허용오차 + 한 눈금))에서 방향만 확인. 경계 사실 {groups} 개가 Related ID 로 HW 블록의 측정 허용오차와 이어졌다 "
        + source + "."
        + (f" 그중 {undecided} 개는 여러 요구가 인용하는 허브 블록 때문에 감시 경로가 하나로 정해지지 않는다(후보를 모두 적고 "
           "가장 큰 허용오차로 밖 점을 정했다)." if undecided else "")
        + (f" {unknown} 개는 HW 블록이 적은 값과 척도가 달라(예: 감시 노드 2.5V) 수치를 쓰지 않았다 — 분압비를 HW 문서로 "
           "확인." if unknown else "")
        # (R50 review I6) the fixed sentence before the narrowing — its guidance ('주면 …') is what the board's tail keeps
        + " 허용오차는 HW 문서 원문 그대로다('Requirement Evidence' HW Tolerance 열, 후보 최대 3 개 · 점은 옮기지 않음)."
        + _hw_narrowing_note(rb),
        tone=_tone(bool(inside)))]


def _design_unused_note(rb: Dict[str, Any], why: str) -> str:
    """(R50 review I5, r4 I-B) A HW design given while the HW requirements it scales were not given or not read: said,
    never dropped — and its own read failure is not hidden behind 'not used'."""
    design = rb.get("hw_design_document")
    if not isinstance(design, dict) or design.get("unused") != "no_hwrs":
        return ""
    if design.get("error"):
        return f" HW 설계서도 읽지 못했다({str(design['error'])[:80]})."
    return f" HW 설계서는 줬지만 그것이 환산할 HW 요구사항서가 {why} 쓰지 않았다."


def _hw_narrowing_note(rb: Dict[str, Any]) -> str:
    """(R50) HSIS 로 감시 경로를 정한 수·HW 설계서 분압식으로 척도를 환산한 수, 그리고 그 입력이 없거나 못 읽었으면 주면
    무엇이 생기는지. R50 이전 산출물엔 키가 없어 아무것도 붙이지 않는다."""
    design = rb.get("hw_design_document")
    hsis = rb.get("hw_hsis")
    if not isinstance(design, dict) and not isinstance(hsis, dict):
        return ""
    parts = []
    n = {k: _int(rb, f"hw_tolerance_{k}") or 0
         for k in ("path_by_hsis", "scaled", "path_refused", "path_outside", "scale_unconfirmed", "scale_net_mismatch",
                   "scale_conflict", "undecided_no_row", "undecided_not_sw", "undecided_row_silent",
                   "undecided_row_ambiguous", "undecided_direct_hub")}
    # (R50 review W2 · W6) what a reader must settle — first
    if n["path_outside"]:
        parts.append(f"HSIS 행의 시스템 ID 를 후보가 아닌 다른 HW 블록도 인용해 경로를 정하지 않은 경계 {n['path_outside']} 개"
                     "(감시 블록이 후보 밖일 수 있음 — 그 블록의 허용오차 확인).")
    if n["path_refused"]:
        parts.append(f"HSIS 행이 가리키는 HW 블록의 이름이 다른 신호라 경로로 쓰지 않은 경계 {n['path_refused']} 개(감시 블록이 "
                     "후보 밖이거나 문서가 서로 다름 — HSIS 와 HW 요구 Related ID 확인).")
    if n["scale_net_mismatch"]:
        parts.append(f"분압식이 HSIS 의 다른 노드라 척도 환산하지 않은 경계 {n['scale_net_mismatch']} 개.")
    if n["scale_conflict"]:
        parts.append(f"문서마다 분압비가 달라 척도 불명인 경계 {n['scale_conflict']} 개.")
    if isinstance(design, dict):
        by = design.get("ratios_by_source") or {}
        # (review W4) a ratio from the HW requirement's own text is not the design's; (r2 I5) a HW design not given or
        #   unread is no "HW 설계서 0" — the requirement's own formulas may still have scaled
        given = design.get("given") is not False and not design.get("error")
        where = (" · ".join(([f"HW 설계서 {by.get('design', 0)}"] if given else []) + [f"HW 요구 자체 식 {by.get('own', 0)}"])
                 if by else f"{design.get('ratios', 0)}")
        if n["scaled"] or any((by or {}).values()):
            parts.append(f"분압식이 있는 감시 노드 블록 {where} 개, 척도를 환산한 경계 {n['scaled']} 개"
                         + (f"(그중 HSIS 네트로 확인 못 한 {n['scale_unconfirmed']} 개)" if n["scale_unconfirmed"] else "")
                         + ".")
    if isinstance(hsis, dict) and hsis.get("given") and not hsis.get("error") and not hsis.get("rows"):
        # (review r2 W1, r3 Info 7) read but no signal, or signals with no SW-variable row: the file or its layout —
        #   never "fix the variable names"
        parts.append(f"HSIS 신호 {hsis.get('signals')} 개를 읽었지만 SW 변수 이름을 적은 행이 없어 감시 경로를 좁히지 "
                     "못했다(SW 변수 열·양식 확인)." if hsis.get("signals") else
                     "HSIS 에서 SW 신호를 하나도 읽지 못해 감시 경로를 좁히지 못했다(파일·양식 확인).")
    elif isinstance(hsis, dict) and hsis.get("given") and not hsis.get("error"):
        why = [f"이 문장의 시스템 블록을 HW 블록 여럿이 인용(허브 — HSIS 를 쓰지 않음) {n['undecided_direct_hub']}"
               if n["undecided_direct_hub"] else "",
               f"주어가 SW 변수가 아님 {n['undecided_not_sw']}" if n["undecided_not_sw"] else "",
               f"SW 변수의 HSIS 행 없음 {n['undecided_no_row']}(이름 확인)" if n["undecided_no_row"] else "",
               f"HSIS 행이 둘 이상 {n['undecided_row_ambiguous']}" if n["undecided_row_ambiguous"] else "",
               f"HSIS 행이 후보 하나만 가진 시스템 ID·네트를 적지 않음 {n['undecided_row_silent']}"
               if n["undecided_row_silent"] else "",
               # (review r4 I-C) the refusals are told above — counted here so the reasons add up to the undecided
               f"후보 밖 블록도 같은 ID 인용 {n['path_outside']}(위)" if n["path_outside"] else "",
               f"HSIS 행과 블록 이름이 다른 신호 {n['path_refused']}(위)" if n["path_refused"] else ""]
        why = [w for w in why if w]
        parts.append(f"HSIS 로 감시 경로를 정한 경계 {n['path_by_hsis']} 개(SW 변수 행 {hsis.get('rows', 0)} 개)"
                     + (" — 경로 미정의 사유: " + " · ".join(why) if why else "") + ".")
    # what to give — last: the gate board keeps the tail (review I6)
    if isinstance(design, dict):
        if design.get("error"):
            parts.append(f"HW 설계서를 읽지 못했다({str(design['error'])[:80]}).")
        elif design.get("given") is False:
            parts.append("HW 설계서(HwDS)를 주면 감시 노드 척도로 적힌 허용오차를 그 분압식으로 환산한다.")
        elif design.get("blocks") == 0:
            # (review r3 Info 5) read, but no HW design table — another document or layout, not "no formula"
            parts.append("HW 설계서에서 설계 표(ID `Hw…`)를 하나도 찾지 못했다 — 다른 문서를 등록했거나 양식이 다르다.")
    if isinstance(hsis, dict):
        if hsis.get("error"):
            parts.append(f"HSIS 를 읽지 못해 SW 신호로 감시 경로를 좁히지 못했다({str(hsis['error'])[:80]}).")
        elif not hsis.get("given"):
            parts.append("HSIS 를 주면 SW 신호의 HSIS 행(시스템 ID·네트 이름)으로 허브의 감시 경로를 좁히고 분압식의 노드를 "
                         "확인한다.")
    return (" " + " ".join(parts)) if parts else ""


def _traced_system_items(rb: Dict[str, Any], why_text: Dict[str, str]) -> List[Dict[str, Any]]:
    """(R29, G4(b)) 시스템 요구 추적 경계 TC. 블록에 `system_documents` 가 없으면 이 기능 전의 산출물이라 항목을
    만들지 않는다(없음과 0 을 구분). 문서를 하나도 안 줬으면 '입력 없음', 못 읽었으면 경고."""
    docs = rb.get("system_documents")
    if not isinstance(docs, list):
        return []
    skips = [str(s) for s in (rb.get("system_input_skips") or [])]
    errors = [d for d in docs if isinstance(d, dict) and d.get("error")]
    read = [d for d in docs if isinstance(d, dict) and "blocks" in d]

    def _n(key):
        return _int(rb, "traced:" + key) or 0
    problems = [f"{d.get('doc')} {d.get('file') or ''} 읽기 실패 — {str(d.get('error'))[:120]}" for d in errors] \
        + [f"로컬화 실패 — {s[:160]}" for s in skips] \
        + [f"{d.get('doc')} {d.get('file') or ''} 에서 시스템 요구 표를 하나도 찾지 못했다(양식이 다르거나 다른 문서)"
           for d in read if not d.get("blocks")]   # (review W3) read but empty is not "no input"
    given = {str(d.get("doc")) for d in docs if isinstance(d, dict)}
    absent = [label for label in ("SyRS", "SyDS") if label not in given]
    if not read:
        return [_item(
            "sts_traced_system_boundary", "시스템 요구 추적 경계 TC", "입력 없음" if not problems else "읽지 못함",
            ("SyRS·SyDS 를 받지 못해 SRS 가 직접 적은 임계만 경계 TC 가 됐다 — SRS 블록의 Related ID 가 가리키는 시스템 "
             "요구의 임계(정본 STS 가 자극으로 쓰는 값 중 SRS 밖의 것)는 시험하지 않았다."
             + (" " + " / ".join(problems) if problems else "")),
            tone=_tone(bool(problems)))]
    # (R51 review r3 W-3) the pass criteria of a cited block are used by the criteria TC — no unused fact
    skipped = {k.split(":", 2)[2]: v for k, v in rb.items() if k.startswith("traced:skipped:") and v
               and k != "traced:skipped:acceptance_criterion"}
    labels = {**why_text, "already_stepped": "SRS·다른 블록에서 이미 시험(같은 주어 표기일 때만)"}
    files = ", ".join(f"{d.get('doc')} {d.get('file') or ''} 블록 {d.get('blocks')}" for d in read)
    by_block = rb.get("traced_facts_by_block") if isinstance(rb.get("traced_facts_by_block"), dict) else {}
    return [_item(
        "sts_traced_system_boundary", "시스템 요구 추적 경계 TC",
        f"TC {_n('tcs')} · 스텝 {_n('steps')} · 사실 {_n('facts_used')} / {_n('facts')}",
        f"SRS 블록의 Related ID 가 **직접** 가리키는 시스템 블록(1 홉, 값으로 찾아 붙이지 않음)의 문장을 요구 원문과 같은 "
        f"규칙으로 읽어 경계 3점을 두었다 — 스텝은 시스템 문장을 인용하고 출처 블록을 적는다('Requirement Evidence' "
        f"시트의 Source Document). 시험 결과(Output 줄·Action·출력 의무)는 자극으로 쓰지 않는다. 문서: {files}"
        + (f" · 받지 않은 문서: {', '.join(absent)}" if absent else "")
        + f". 인용 {_n('cited')} 회 중 문서에 없는 ID {_n('cited_not_in_documents')}."
        # (R47 review I4) SyDS 요소의 입력 칸(Input Information)은 R47 부터 — 따로 세어 R47 전후 비율을 읽게 한다
        + (f" 추적 TC {_n('tcs')} 중 요소 입력 칸(Input Information) TC {_n('input_range_tcs')} · 스텝 "
           f"{_n('input_range_steps')} · 사실 "
           f"{_n('input_range_facts_used')} — 입력이 그 칸이 적은 범위 안인지 밖인지만 적고, 요소의 반응(이상 판정·리셋)은 "
           "같은 요구의 다른 문장 판정을 따른다." if _n("input_range_facts_used") else "")
        + (" 사실을 가장 많이 낸 블록: " + ", ".join(f"{k} {v}" for k, v in list(by_block.items())[:5])
           + f" (블록 {_int(rb, 'traced_blocks_used') or len(by_block)} 개 — 여러 요구가 같은 블록을 인용하면 요구마다 "
             "다시 시험한다)." if by_block else "")
        + (" 못 쓴 사실: " + ", ".join(f"{labels.get(k, k)} {v}" for k, v in sorted(skipped.items())) + "."
           if skipped else "")
        + (" " + " / ".join(problems) if problems else ""),
        tone=_tone(bool(problems)))]


def _sts_tail_items(qr: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    # 안전 관련 TC — 분모(전체 TC)와 함께 둬야 "142건" 이 많은지 적은지 읽힌다.
    safety_tc = _int(qr, "safety_test_cases")
    if safety_tc is not None:
        total = _int(qr, "total_test_cases")
        out.append(_item(
            "sts_safety_test_cases", "안전 관련 TC",
            f"{safety_tc} / {total}" if total is not None else str(safety_tc),
            "ASIL 이 붙은 요구·함수를 겨눈 시험 수다. 분모는 이 문서의 전체 TC 다."))
    return out


# (R7) 인터페이스 제안 값의 근거·못 정한 사유 — 영문 키를 화면에 그대로 내지 않는다(리뷰 r2 Info 6)
_SITS_BASIS = {"return_type_bounds": "반환 타입 경계", "compared_value_and_neighbour": "비교 상수와 이웃",
               "enum_sibling": "열거 형제", "truth_value": "참/거짓"}
_ERROR_BASES = {"compared_value_and_neighbour", "enum_sibling", "truth_value"}
_SITS_SKIP = {"compared_value_unresolved": "비교 상수 미해석", "switch_cases_not_modeled": "switch 분기 미모델",
              "enum_has_no_other_value": "다른 값이 없는 열거", "neighbour_outside_return_type": "이웃 값이 반환 타입 밖",
              "return_type_bounds_unknown": "반환 타입 범위 미상"}


# ── SUTS ───────────────────────────────────────────────────────────────────
def _suts_items(qr: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    # (R9) 기대값 근거 — 확정값은 소스 계산(derived)뿐이고 나머지는 [검증 필요] 다. 실행 결과가 아니다.
    ev = qr.get("expected_evidence_summary")
    if isinstance(ev, dict) and _int(ev, "total") is not None:
        out.append(_item(
            "suts_expected_evidence", "기대값 근거",
            f"소스 계산 {_show(_int(ev, 'derived'))} (함수가 쓴 값 {_show(_int(ev, 'derived_assigned'))} · 입력 그대로 "
            f"{_show(_int(ev, 'derived_unchanged_input'))}) · 미상 {_show(_int(ev, 'unknown'))} · 제안 "
            f"{_show(_int(ev, 'proposed'))} · 근거 미기록 {_show(_int(ev, 'unrecorded'))} / 전체 {_show(_int(ev, 'total'))}칸",
            "확정 기대값은 소스 oracle 이 함수 본문을 해석해 낸 값만이다(요구 적합성·타깃 실행은 아님 — "
            "execution_status=not_run). 나머지 칸은 [검증 필요] 와 사유를 적었다. 근거는 'Test Evidence' 시트에 있다."
            + (f" 그중 {_int(ev, 'derived_in_stubbed_sequence')}칸은 피호출 함수의 반환값을 시퀀스 입력"
               "('F() return')으로 stub 한 시퀀스에서 나왔다 — 시험도 그 함수를 stub 해야 성립한다(같은 유닛의 함수는 "
               "Stub-By-Function 으로; stub 은 반환값만 주고 전역·정적 변수를 쓰지 않는다고 본다; 포인터 인자로 써 넣는 "
               "값은 미상. 시퀀스 단위로 센 상한)."
               if _int(ev, "derived_in_stubbed_sequence") else "")
            # (R17) 빌드 설정 증거로 #if 를 판정한 unit 의 칸 — 그 unit 의 가정 이름을 모두 싣는다(상한)
            + (f" {_int(ev, 'derived_on_assumed_undefined')}칸은 빌드 설정 증거로 '정의 없음'이라 본 이름에 기댄 #if 판정이 있는 "
               "unit 의 값이다 — unit 단위로 센 상한이라 그 판정이 값에 닿지 않은 칸도 포함한다(아래 '빌드 설정 매크로 판정')."
               if _int(ev, "derived_on_assumed_undefined") else "")))

    # (R10) 소스 소견 — 기대값을 내다가 증명한 미정의 동작. 결함 **후보**다(입력이 호출 측에서 가능한지는 사람 판단).
    sf = qr.get("source_findings")
    if isinstance(sf, dict) and _int(sf, "findings") is not None:
        kinds = sf.get("by_kind") if isinstance(sf.get("by_kind"), dict) else {}
        out.append(_item(
            "suts_source_findings", "소스 소견(결함 후보)",
            f"소견 {_show(_int(sf, 'findings'))} (함수 {_show(_int(sf, 'functions'))} · 시퀀스 {_show(_int(sf, 'sequences'))})",
            "소스 oracle 이 기대값을 계산하다 이 입력에서 적어도 한 실행 경로가 C 미정의 동작(부호 오버플로·0 나눗셈 등)에 "
            "닿는 것을 찾은 곳이다(입력이 정하지 않은 조건의 분기일 수 있다). 입력이 호출 측에서 실제로 가능한지는 확인이 "
            "필요하다 — 'Source Findings' 시트에 예시 벡터가 있다."
            + (" 종류: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) + "." if kinds else "")
            + " clang 재현은 scripts/source_findings.py --clang 으로 따로 돌린다(이 문서에서는 미실행).",
            tone=_tone(bool(_int(sf, "findings")))))
        # (R19) 입력 목록 밖 읽기 — 같은 시트의 다른 종류(`read_not_in_unit_inputs`), 미정의 동작 소견 수에 넣지 않는다
        gaps = sf.get("input_list_gaps")
        if isinstance(gaps, dict) and _int(gaps, "functions") is not None:
            out.append(_item(
                "suts_input_list_gaps", "입력 목록 밖 읽기",
                f"함수 {_show(_int(gaps, 'functions'))} · 객체 {_show(_int(gaps, 'names'))}",
                "함수가 초기값을 읽는데(이 입력으로 돌리면 쓰기 전에 읽는다) 시험 입력 목록(설계서 입력 표·소스 분석)에 없는 "
                "프로그램 객체다 — 설계서 입력 누락 또는 입력으로 적지 않은 내부 상태 후보. 'Source Findings' 시트의 "
                "`read_not_in_unit_inputs` 행에 함수별 이름이 있다. 확장 프로파일은 이 객체를 입력 열로 더했다('소스가 읽어 더한 "
                "입력').",
                tone=_tone(bool(_int(gaps, "functions")))))

    # (R9) MC/DC 설계 — 결정식을 실제로 평가해 찾은 unique-cause 쌍. 못 푼 결정은 분모에 남는다.
    mc = qr.get("mcdc_design_summary")
    if isinstance(mc, dict) and _int(mc, "decisions") is not None:
        path = mc.get("source_path") if isinstance(mc.get("source_path"), dict) else {}
        out.append(_item(
            "suts_mcdc_design", "MC/DC 설계",
            f"결정 {_show(_int(mc, 'decisions'))} 중 설계 {_show(_int(mc, 'designed'))} · 부분 "
            f"{_show(_int(mc, 'partial'))} · 쌍 못 찾음 {_show(_int(mc, 'no_pair_found'))} · 미지원 "
            f"{_show(_int(mc, 'unsupported'))} · 유지 쌍 {_show(_int(mc, 'retained_pairs'))}"
            + (f" (함수 실행 모델로 설계한 결정 {_show(_int(path, 'designed'))} / {_show(_int(path, 'decisions'))})"
               if path else ""),
            "쌍은 소스 결정식을 평가해 찾은 설계다 — 도달성·타깃 실행은 주장하지 않는다(reachability=unverified). "
            "행 상한에 잘린 쌍은 '절단', 재검증에서 떨어진 쌍은 '무효' 로 따로 센다"
            + (f"(절단 {_show(_int(mc, 'truncated_pairs'))} · 무효 {_show(_int(mc, 'invalidated_pairs'))})."
               if _int(mc, "truncated_pairs") is not None else ".")
            # (R56 리뷰 I1) 어느 예산으로 설계했는지 — 같은 소스라도 예산이 다르면 쌍이 다르다
            + _mcdc_budget_text(mc.get("path_search_budget"))
            + (f" 결정을 나열하지 못한 함수 {_show(_int(mc, 'unenumerated_functions'))} · 분석하지 못한 unit "
               f"{_show(_int(mc, 'units_not_analyzed'))} 는 위 분모 밖이다."
               if (_int(mc, "unenumerated_functions") or _int(mc, "units_not_analyzed")) else "")
            + (f" 피호출 함수의 stub 반환값(`F() return` 칸)을 넣어 짝지은 조건이 있는 결정 "
               f"{_show(_int(mc, 'stub_input_decisions'))} · 그런 쌍 {_show(_int(mc, 'stub_input_pairs'))}(행 상한 뒤 유지 "
               f"{_show(_int(mc, 'stub_input_pairs_retained'))}) — 그 행은 해당 함수를 stub 으로 실행할 때만 성립한다"
               "('Stub Inputs' 열). stub 값 탐색은 1차 탐색이 설계하지 못한 결정에만, 별도 예산으로 돈다"
               f"(대상 결정 {_show(_int(mc, 'stub_search_decisions'))} · 조건을 더한 결정 "
               f"{_show(_int(mc, 'stub_search_improved'))}"
               + (f" · 탐색 실패로 1차 결과를 유지한 함수 {_show(_int(mc, 'stub_search_errors'))}"
                  if _int(mc, "stub_search_errors") else "")
               + "); 1차 탐색의 MC/DC 쌍과 행은 바뀌지 않는다 — 다만 행 상한이 찬 TC 에서는 새 MC/DC 행이 경계 행을 "
               "밀어낼 수 있다(stub 값 탐색 예산은 함수당 그룹별)."
               if _int(mc, "stub_input_decisions") else "")
            # (R37) outside the stub clause: a call-condition decision may be designed without a stub (or not at all)
            + (f" 조건 안에 호출이 있는 결정 {_show(_int(mc, 'call_condition_decisions'))} 은 다른 결정과 따로, 별도 "
               f"예산으로 탐색했다(설계 {_show(_int(mc, 'call_condition_designed'))} — 함수 호출은 행이 그 피호출을 "
               "stub 할 때만 관측한다(stub 은 전역·정적 변수를 쓰지 않는다; 부작용 없는 함수형 매크로는 stub 없이 관측): "
               "포인터 인자로 값을 써 넣을 수 있는 피호출(행이 출력 인자를 설정 · 쓰기 closure 의 포인터 쓰기 · 알 수 없는 "
               "피호출)·이름 가림·"
               "stub 없음·조건 안의 쓰기·효과 있는 매크로·평가 순서가 정해지지 않은 식 등은 관측하지 않는다)."
               if _int(mc, "call_condition_decisions") else "")
            # (R39) conditions on struct members: the members are inputs of their own name (``g.a``)
            + (f" 구조체 멤버(`g.a` — 정본 표기와 같은 입력 이름)를 읽는 조건의 결정 "
               f"{_show(_int(mc, 'member_condition_decisions'))} 도 따로, 별도 예산으로 탐색했다(설계 "
               f"{_show(_int(mc, 'member_condition_designed'))} — 포인터 매개변수가 아닌 포인터를 거친 멤버(`p->a`)·"
               "구조체 배열·공용체·비트필드 멤버는 모델링하지 않는다)."
               if _int(mc, "member_condition_decisions") else "")
            # (R40) conditions through a pointer parameter: its pointee is an input of its own name (``p[0].a``)
            + (f" 포인터 매개변수가 가리키는 대상(`p[0].a` · `p[0]` — 정본 표기와 같은 입력 이름)을 읽는 조건의 결정 "
               f"{_show(_int(mc, 'pointee_condition_decisions'))} 도 따로, 별도 예산으로 탐색했다(설계 "
               f"{_show(_int(mc, 'pointee_condition_designed'))} — 대상은 행이 그 값을 설정할 때만 하네스가 따로 할당한 "
               "널 아닌 객체로 본다: 그래서 널 검사(`p != NULL`)는 모든 행에서 한쪽이라 짝이 없다. 식 엔진이 다른 이유"
               "(지역 변수·조건 안 호출)로 먼저 거부한 결정은 그 이유의 탐색으로 가며 대상 입력을 설정하지 않는다)."
               if _int(mc, "pointee_condition_decisions") else "")
            # (R58) the extended profile's second design over the inputs the source reads
            # (리뷰 R58 W2 · 3차 W-1) 실패만 있어도 말하고, 숫자는 부분마다 따로 — 빈 부분은 쓰지 않는다
            + (_source_read_pass_text(mc)
               if (_int(mc, "source_read_pass_decisions") or _int(mc, "source_read_pass_errors")) else "")
            # (R60) whether the two rows of a retained pair differ in an output the function wrote (Observable MC/DC, measured)
            + (_observable_text(mc) if any(_int(mc, k) for k in (
                "observable_pairs", "observable_searched", "observable_masked", "observable_underived",
                "observable_recheck_refused", "observable_no_candidate", "observable_copy_only",
                "observable_budget_exhausted", "observable_not_checked",
                "observable_evidence_mismatch", "observable_errors")) else "")
            + " 결정별 근거는 'MCDC Design' 시트에 있다.",
            tone=_tone(bool(_int(mc, "invalidated_pairs")) or bool(_int(mc, "source_read_pass_errors"))
                       or bool(_int(mc, "observable_evidence_mismatch")) or bool(_int(mc, "observable_errors")))))

    # 비운 칸 — **결함이 아니다**(info). 예전엔 이 칸을 전부 uint8 로 지어낸 0/127/255 로 채웠다.
    unk = _int(qr, "unknown_type_var_slots")
    if unk is not None:
        units = _int(qr, "units_with_unknown_type_vars")
        out.append(_item(
            "suts_unknown_type_slots", "타입을 몰라 비운 칸", f"{unk}칸"
            + (f" ({units}개 unit)" if units is not None else ""),
            "변수 선언은 찾았지만 타입 폭을 확정하지 못해 입력/기대값을 비워 둔 자리다. 빠뜨린 게 아니라 "
            "지어내지 않은 것이고, 이 칸은 사람이 채운다."))

    # 경계값을 무엇이 정했나 — 설계서 범위가 정한 칸과 타입 전폭으로 때운 칸은 신뢰도가 다르다.
    if isinstance(qr.get("bounds_source_distribution"), dict):
        out.append(_item(
            "suts_bounds_source", "경계값 출처 분포", _dist(qr["bounds_source_distribution"]) or "(0칸)",
            "uds_range=설계서가 적은 값 범위 · uds_values=설계서가 적은 값 목록(R65) · enum=열거자 값 집합 · "
            "hsis=HSIS 범위 · type=선언 타입의 전폭 · "
            "unknown=비운 칸. type 비중이 크면 값은 유효하지만 설계 의도가 아니라 타입이 정한 경계다."))

    # 설계서 범위와 선언 타입이 어긋난 변수 — 문서 쪽 오류일 수 있어 사람이 봐야 한다.
    conflicts = _int(qr, "range_conflict_count")
    if conflicts is not None:
        note = "설계서가 적은 값 범위 · 값 목록이 선언(타입 폭 · 열거자)과 맞지 않는 변수다."
        if conflicts:
            head = _head(qr.get("range_conflicts"))
            note += f" 예: {head}" if head else ""
            note += " — 설계서와 소스 중 한쪽이 틀렸다는 뜻이라 값을 고르지 않고 선언(타입 폭 · 열거자)으로 시험했다."
        else:
            note += " 어긋난 변수가 없다 — 설계서 범위와 선언이 서로 맞는다."
        out.append(_item("suts_range_conflicts", "범위 충돌", f"{conflicts}건", note, tone=_tone(conflicts > 0)))

    # 포인터 주소 범위 — 위 충돌과 **다른 축**이라 따로 센다(문서 오류가 아니다).
    ptr = _int(qr, "pointer_address_range_count")
    if ptr is not None:
        out.append(_item(
            "suts_pointer_address_ranges", "포인터 주소 범위", f"{ptr}건",
            "설계서가 포인터 인자에 주소 공간(0~4294967295)을 적은 자리다. 문서 오류가 아니라 다른 축이라 "
            "범위 충돌에서 뺐고, 값은 선언 타입 폭으로 시험한다."))

    # [검증 필요] 마커가 붙은 칸 — 마커는 정직하지만 몇 칸인지는 어디에도 없었다(R76 N95).
    verify = _int(qr, "verify_needed_expected_slots")
    if verify is not None:
        out.append(_item(
            "suts_verify_needed", "기대값 미상 칸", f"{verify}칸",
            "범위를 벗어난 입력에 대해 소스가 어떻게 답하는지 정할 근거가 없어 `[검증 필요]` 로 남긴 칸이다. "
            "시험 실행 전에 사람이 기대값을 정해야 한다."))

    # 요구 ID 가 무슨 근거로 붙었나.
    if isinstance(qr.get("srs_req_link_distribution"), dict):
        linked = _int(qr, "units_with_srs_req_ids")
        out.append(_item(
            "suts_srs_req_link", "요구 ID 연결 근거",
            _dist(qr["srs_req_link_distribution"]) or "(0건)",
            "sds_partition=설계서 파티션 매칭 · sts_mapping=STS 의 요구↔함수 매핑 재사용 · hsis=HSIS 경유 · "
            "unrecorded=근거 미기록."
            + (f" 요구 ID 가 붙은 unit 은 {linked}개다." if linked is not None else "")))

    # 등급의 근거 분포 — `none` 은 "근거 없음(TBD)" 이지 QM 이 아니다.
    if isinstance(qr.get("asil_evidence_distribution"), dict):
        dist = qr["asil_evidence_distribution"]
        none_cnt = _int(dist, "none") or 0
        out.append(_item(
            "suts_asil_evidence", "ASIL 근거 분포", _dist(dist) or "(0건)",
            "uds=SwUDS 표가 정한 등급 · source=소스 주석 @asil · override=저장소 스냅샷(프로젝트 확인 없음) · "
            "sds-*=설계서 파티션 · none=근거 없음."
            + (f" 근거 없는 unit 이 {none_cnt}개다 — 등급을 지어내지 않고 비운 것이라 사람이 정해야 한다."
               if none_cnt else ""),
            tone=_tone(none_cnt > 0)))

    # 소스에 없는 override 전용 unit — 정상값이 0 이라 0 에서는 감춘다(0 을 보이면 늘 붙어 다니는 잡음이 된다).
    ovr = _int(qr, "override_only_unit_count") or 0
    if ovr:
        out.append(_item(
            "suts_override_only", "소스에 없는 unit", f"{ovr}개",
            "저장소 스냅샷에만 있고 이번 소스에서는 찾지 못한 함수다 — 스냅샷이 낡았거나 함수가 삭제됐다."
            + (f" 예: {_head(qr.get('override_only_units'))}" if qr.get("override_only_units") else ""),
            tone="warning"))

    # 설계 근거 보강 단계 실패 — 있으면 그 단계의 값이 통째로 빠진 채 문서가 나갔다는 뜻이다.
    errs = qr.get("enrichment_errors")
    if isinstance(errs, list):
        if errs:
            first = errs[0] if isinstance(errs[0], dict) else {}
            out.append(_item(
                "suts_enrichment_errors", "설계 근거 보강 실패", f"{len(errs)}건",
                f"단계 `{first.get('stage', '?')}` 가 실패해 건너뛰었다 — {str(first.get('error', ''))[:160]}. "
                "그 단계가 채웠을 값(설계서 범위·요구 ID 등)이 이 문서에 없다.",
                tone="warning"))
        else:
            out.append(_item(
                "suts_enrichment_errors", "설계 근거 보강 실패", "0건",
                "설계서·HSIS 보강 단계가 전부 끝까지 돌았다 — 빈 칸이 있다면 근거가 없어서지 실패 때문이 아니다."))

    # 확장 증분 — 기본 프로파일이면 0 이 정상이라 감춘다.
    ext_seq = _int(qr, "extended_sequences")
    beyond = _int(qr, "sequences_beyond_reference_cap")
    if ext_seq or beyond:      # 둘 다 0/미기록이면 감춘다(항목 존재 조건)
        out.append(_item(
            "suts_extended", "확장으로 덧붙인 시퀀스",
            f"확장 전략 {_show(ext_seq)} · 상한 해제분 {_show(beyond)}",
            "확장 전략이 새로 만든 시퀀스와, 기본 카탈로그 안에 있었지만 시퀀스 상한에 잘리던 자리다. "
            "둘을 합치면 기본 문서 대비 증분이다."))

    # (R15) 행동 경계 행 — 확장 프로파일에서만 기록된다(기본 문서엔 키가 없어 항목도 없다).
    bs = qr.get("boundary_search")
    if isinstance(bs, dict):
        skipped = bs.get("not_searched") if isinstance(bs.get("not_searched"), dict) else {}
        out.append(_item(
            "suts_boundary_rows", "행동 경계 행",
            f"{_show(_int(qr, 'boundary_rows'))}행 · 경계 {_show(_int(bs, 'boundaries'))} · 탐색한 unit "
            f"{_show(_int(bs, 'searched'))}/{_show(_int(bs, 'units'))} (행이 붙은 unit {_show(_int(bs, 'with_rows'))})",
            "입력 하나를 움직여 소스 oracle 이 도출한 출력이 계단처럼 바뀌는 인접한 두 값을 찾아 행으로 **더한** 것이다(기존 "
            "행은 옮기지 않는다). 기대값은 다른 행과 같은 oracle 이 도출한다 — 모델 탐색이지 실행이 아니다. 기준 행이 비운 "
            "입력은 선언 범위의 중간값 근처로 채우고 행 설명에 그 값을 적는다. enum 은 열거자 값만 쓴다. 기준 행이 상한보다 "
            "많으면 서로 다른 출력 상태에 이르는 행을 먼저 쓴다. "
            + (f"탐색하지 못한 unit: {_dist(skipped)}. " if skipped else "")
            + (f"경계 탐색에 들어가지 않은 unit {_show(_int(bs, 'units_without_search'))}(입출력 없는 unit 경로). "
               if _int(bs, "units_without_search") else "")
            + (f"예산을 다 쓴 unit {_show(_int(bs, 'budget_exhausted'))}(평가 상한 "
               f"{_show(_int(bs, 'evaluation_budget_exhausted'))} · 경계 상한 {_show(_int(bs, 'boundary_cap_reached'))})"
               " 은 경계를 더 가질 수 있다. " if _int(bs, "budget_exhausted")
               else "예산을 다 쓴 unit 은 없다. " if _int(bs, "budget_exhausted") == 0 else "")
            + (f"기준 행 상한에 잘린 unit {_show(_int(bs, 'bases_capped'))} · 상수 상한에 잘린 unit "
               f"{_show(_int(bs, 'constants_capped'))} · 너무 커서 움직이지 않은 값 집합 "
               f"{_show(_int(bs, 'value_sets_capped'))}."
               if any(_int(bs, k) for k in ("bases_capped", "constants_capped", "value_sets_capped")) else "")
            + (f" 탐색 중 오류로 경계 행 없이 둔 unit {_show(_int(skipped, 'error'))} — 로그에 traceback 이 있다."
               if _int(skipped, "error") else ""),
            # (리뷰 2라운드 W4) 오류로 건너뛴 unit 이 있으면 경고 — 행 수가 줄어든 것만으로는 버그가 안 보인다
            tone=_tone(bool(_int(bs, "budget_exhausted")) or bool(_int(skipped, "error")))))
    # (R23) 입력이 같은 TC 의 앞 행과 똑같은 행 — 두 프로파일. 둘 다 0 이면 감춘다.
    dr = qr.get("duplicate_rows")
    if isinstance(dr, dict) and (_int(dr, "reference_rows_duplicated") or _int(dr, "extended_rows_dropped")
                                 or _int(dr, "extended_rows_duplicated_kept")):
        out.append(_item(
            "suts_duplicate_rows", "입력이 앞 행과 같은 행",
            f"정본 규모 행 {_show(_int(dr, 'reference_rows_duplicated'))}(unit {_show(_int(dr, 'units_with_reference_duplicates'))},"
            f" 남김) · 확장 행 {_show(_int(dr, 'extended_rows_dropped'))}(뺌)",
            "같은 TC 안에서 입력이 앞 행과 똑같은 행은 기대값도 같아(결정적 oracle) 새 정보가 없다. 정본 규모 카탈로그 행은 전략별 "
            "자리(경계값·조건 조합·루프 …)가 정본 문서와 같아야 해 남기고 센다 — 예: 입력이 하나인 unit 의 MIXED 는 BV_MIN 과 같고, "
            "타입을 몰라 값을 비운 입력만 있는 unit 은 여러 행이 빈 입력이다. 확장 전략 행(단독 경계 OAT·기본 자리를 넘는 "
            "switch/GLOBAL)은 근거를 계산하기 전에 뺐다 — 예: 0/1 플래그의 최솟값은 중간값과 같아 OAT_MIN 이 BV_MID 와 겹친다. "
            "MC/DC 설계 벡터 행은 쌍이 벡터로 행을 찾으므로 빼지 않는다"
            + (f"(앞 행과 같아 남긴 확장 MC/DC 행 {_show(_int(dr, 'extended_rows_duplicated_kept'))})."
               if _int(dr, "extended_rows_duplicated_kept") else ".")
            + (" 확장 문서의 '정본 규모 행' 에는 정본 규모 상한을 넘어 이어지는 기본 카탈로그 행도 들어 있다."
               if qr.get("tc_profile") == "extended" else "")))
    # (R21) 행이 설정해 열로 보인 입력·기대값 — 두 프로파일. 0 이면 감춘다(항목 존재 조건).
    ri = qr.get("row_io_columns")
    if isinstance(ri, dict) and (_int(ri, "inputs_shown") or _int(ri, "outputs_shown") or _int(ri, "downgraded_slots")):
        out.append(_item(
            "suts_row_io_columns", "행이 설정해 열로 보인 이름",
            f"입력 {_show(_int(ri, 'inputs_shown'))}(unit {_show(_int(ri, 'units_with_inputs_shown'))}) · 기대값 "
            f"{_show(_int(ri, 'outputs_shown'))}(unit {_show(_int(ri, 'units_with_outputs_shown'))})",
            "GLOBAL 행(간접 변수를 최솟값으로)과 입출력 없는 unit 의 호출 시퀀스가 설정·기대하는 간접 변수(전역·레지스터 필드·"
            "멤버 경로 포함)를 TC 의 입력·기대값 열로 보였다 — 예전 문서는 이 값을 싣지 않아 기대값이 문서에 없는 자극에 기댔다. "
            "값은 그것을 설정한 행(GLOBAL 행, 확장 프로파일에선 그 행을 기준으로 한 경계 행)에만 있고 다른 행은 비어 있다(설정하지 "
            "않음 — 그 행들은 이 이름에 기댄 확정값이 없다). 호출 시퀀스의 오류 경로 행은 BV_*_INV 처럼 형 밖 값을 싣는다. "
            "열이 늘어 TC 의 입출력 변수 수·'입출력 없는 TC' 수·생성 방법 표기가 예전 문서와 달라진다(기본 프로파일도 설계서 입력 "
            "표보다 열이 많다). 같은 이름을 다른 행이 값 없이 읽으면 '입력 목록 밖 읽기' 소견에도 남는다."
            + (f" 입력 열 상한 때문에 보이지 못한 입력 {_show(_int(ri, 'inputs_over_cap'))} — 그 입력을 쓰는 행의 확정 칸 "
               f"{_show(_int(ri, 'downgraded_slots'))}을 [검증 필요](input_not_in_document)로 내렸다."
               if _int(ri, "inputs_over_cap") else "")
            + (f" 기대값 열 상한 때문에 보이지 못한 기대값 {_show(_int(ri, 'outputs_over_cap'))}(단언하지 않음)."
               if _int(ri, "outputs_over_cap") else ""),
            tone=_tone(bool(_int(ri, "inputs_over_cap")))))
    # (R19) 소스가 읽어 더한 입력 — 확장 프로파일에서만 기록된다. 설계서 입력 목록과 열이 달라지므로 늘 공시한다.
    sr = qr.get("source_read_inputs")
    if isinstance(sr, dict):
        not_added = sr.get("not_added") if isinstance(sr.get("not_added"), dict) else {}
        out.append(_item(
            "suts_source_read_inputs", "소스가 읽어 더한 입력",
            f"unit {_show(_int(sr, 'units_with_added'))}/{_show(_int(sr, 'units'))} · 이름 {_show(_int(sr, 'names_added'))}"
            f" · 남은 이름 {_show(_int(sr, 'names_remaining'))}",
            "소스 oracle 이 '초기값이 입력에 없다' 고 답한 객체(함수가 이 행으로 돌면 쓰기 전에 읽거나, 쓰지 않은 경로에서 최종값이 "
            "초기값인 출력)를 번역 단위의 선언 타입으로 "
            "입력 열에 더하고 행을 다시 만들었다 — 설계서 입력 표와 다른 열이다."
            + (f" 그중 {_show(_int(sr, 'names_added_for_unwritten_outputs'))} 이름은 함수 실행 모델에서 읽힌 근거가 없고, 어떤 "
               "경로에서 쓰지 않은 출력의 최종값(=초기값)을 기대값으로 적으려고 더했다 — 입력 목록 결손 소견에는 넣지 않는다("
               "모델이 읽음을 귀속하지 못하면 읽은 것으로 둔다 — 해석하지 않는 피호출 함수는 본문 · 매크로가 이름 붙인 객체와 "
               "포인터로 닿는 객체를, 대상을 모르는 포인터 읽기는 포인터로 닿는 객체를, 해석하지 않는 매크로는 정의가 이름 붙인 "
               "객체를, 정의를 모르는 함수 · 인라인 어셈블리는 모든 객체를 읽은 것으로 본다)."
               if _int(sr, "names_added_for_unwritten_outputs") else "") + " 기본 카탈로그 행의 자리·순서·설계 열 값은 정본 규모 "
            "문서와 같고 그 행에서 더한 입력은 고정값이다. 더한 입력의 범위(선언 타입 전폭, enum 은 그 번역 단위의 열거자 — 설계서·"
            "HSIS 는 이 이름을 적지 않았다)는 단독 경계(OAT)·행동 경계 행이 움직인다. 더한 입력이 연 경로에서 새로 보인 이름은 다음 "
            f"회차에 더한다(최대 {_show(_int(sr, 'max_rounds'))}회차 사용"
            + (f" · 상한 {_show(_int(sr, 'round_cap'))}회차" if _int(sr, "round_cap") else "")
            + (f" · 상한에서 멈춰 다음 회차가 더했을 이름 {_show(_int(sr, 'names_beyond_cap'))}"
               f"(unit {_show(_int(sr, 'units_round_cap_reached'))}) — 그 이름을 읽는 칸은 [검증 필요]로 남는다"
               if _int(sr, "units_round_cap_reached") else "")
            + "). 지역·매개변수·멤버 경로·const·volatile·부동소수 "
            "객체와 경계값 표가 없는 타입(64비트 등)은 더하지 않는다"
            + (f"(더하지 않은 사유: {_dist(not_added)})" if not_added else "") + ". "
            + (f"입력 열 상한에 막힌 unit {_show(_int(sr, 'units_input_columns_full'))}. "
               if _int(sr, "units_input_columns_full") else "")
            + (f"마지막 회차에도 남은 이름 {_show(_int(sr, 'names_remaining'))}(unit {_show(_int(sr, 'units_with_remaining'))})"
               " 은 그 칸을 [검증 필요] 로 둔다. " if _int(sr, "names_remaining") else "")
            + "MC/DC 설계 벡터는 결정이 읽는 입력만 적으므로 더한 열이라도 그 행에선 비어 있을 수 있다(기본 MC/DC 설계는 "
            "설계 입력 목록 위에서 하고, 그 설계가 쌍을 못 만든 결정만 더한 입력까지 써서 다시 설계한다 — 'MC/DC 설계' 항목·"
            "'Input Scope' 열)."
            + (f" 입력 보완 중 오류로 설계 입력 목록 그대로 둔 unit {_show(_int(sr, 'errors'))} — 로그에 traceback 이 있다."
               if _int(sr, "errors") else ""),
            tone=_tone(bool(_int(sr, "units_input_columns_full")) or bool(_int(sr, "errors"))
                       or bool(_int(sr, "units_round_cap_reached")))))
    # (R19) MC/DC 채움 행 — 확장 프로파일에서만 기록된다
    mf = qr.get("mcdc_fill")
    if isinstance(mf, dict):
        out.append(_item(
            "suts_mcdc_fill_rows", "MC/DC 채움 행",
            f"{_show(_int(mf, 'rows'))}행 (공란이 있는 MC/DC 벡터 {_show(_int(mf, 'rows_with_blanks'))}/"
            f"{_show(_int(mf, 'mcdc_rows'))})",
            "MC/DC 설계 벡터는 결정이 읽는 입력만 적어 나머지 칸이 비고, 함수가 그 입력을 읽으면 기대값이 서지 않는다. 벡터 행은 "
            "그대로 두고 비운 입력을 행동 경계 행과 같은 규칙(선언 타입 범위의 중간값에서 입력 위치만큼 옮긴 값, enum 은 열거자 — "
            "이름 패턴으로 추측한 타입은 채우지 않는다)으로 채운 행을 더했다 — MC/DC 쌍의 구성원이 아니며(쌍 주장은 원래 행에만 "
            "있다) 기대값은 다른 행과 같은 oracle 이 도출한다. 원래 벡터보다 더 도출하는 칸이 없는 채움 행은 뺐다."
            + (f" 더 도출하는 칸이 없어 뺀 행 {_show(_int(mf, 'pruned'))}." if _int(mf, "pruned") else "")
            + (f" 선언 타입이 없어 채우지 못한 벡터 {_show(_int(mf, 'not_fillable'))}." if _int(mf, "not_fillable") else "")
            + (f" 채운 결과가 이미 있는 행과 같아 더하지 않은 것 {_show(_int(mf, 'duplicates'))}."
               if _int(mf, "duplicates") else "")
            + (f" 채움 단계 오류로 채움 행 없이 둔 unit {_show(_int(mf, 'errors'))} — 로그에 traceback 이 있다."
               if _int(mf, "errors") else ""),
            tone=_tone(bool(_int(mf, "errors")))))
    # (R31) 설계 범위 밖 강건성 행 — 확장 프로파일에만 있다
    rr = qr.get("robustness_rows")
    if isinstance(rr, dict):
        out.append(_item(
            "suts_robustness_rows", "설계 범위 밖 강건성 행",
            f"{_show(_int(rr, 'rows'))}행 (unit {_show(_int(rr, 'units_with_rows'))} · 설계 범위·선언 타입이 있는 입력 "
            f"{_show(_int(rr, 'inputs_with_design_range'))} · 설계 범위 밖 직접 비교 상수 "
            f"{_show(_int(rr, 'compared_constants_outside_design'))}, 살아 있는 기준 {_show(_int(rr, 'live'))})",
            "설계서·HSIS 가 입력 범위를 정했는데 소스가 그 입력을 범위 밖·선언 타입 안의 상수와 직접 비교하는 곳(예: 설계 범위 "
            "0~60 인 타이머를 `< u16g_MAX` 로 포화 보호)에, 그 상수의 −1·0·+1 중 설계 범위 밖·타입 안 값으로 입력 하나만 바꾼 "
            "FI 행을 더했다 — 코드 상수에서 나온 경계값이다. 행의 기준은 그 비교가 **살아 있는**(그 점들에서 도출 출력이 한 "
            "기울기로 움직이지 않는) 기존 행을 먼저 찾아 쓰고, 못 찾으면 첫 기준 행이다(값의 '살아 있는 기준' 이 찾은 상수 수). 기대값은 다른 행과 같은 소스 oracle 이 도출한 코드 일관성 값이지 설계 적합성이 "
            "아니다(설계는 그 값을 허용하지 않는다). oracle 이 출력을 하나도 도출하지 못하는 점은 행으로 만들지 않는다."
            + (f" 비교가 살아 있는 기준 행을 못 찾은 상수 {_show(_int(rr, 'not_live'))} — 그 점은 첫 기준 행에 두었고(도출되는 "
               "점만 행이 된다) 비교에 닿지 않을 수 있다(가드 조건이 기준 행에서 거짓이거나 출력을 도출하지 못함, 행 설명에도 "
               "적었다)." if _int(rr, "not_live") else "")
            + (f" 본문을 확정하지 못한 매크로의 인자 안에서만 나온 비교라 이 빌드에 있는지 확인하지 못해(살아 있는 기준 행을 못 "
               f"찾았거나 점이 셋 미만) 쓰지 않은 상수 {_show(_int(rr, 'macro_argument_unconfirmed'))}."
               if _int(rr, "macro_argument_unconfirmed") else "")
            + (f" 본문을 확정하지 못한 매크로의 인자 안에서만 나온 비교 중 살아 있는 기준 행에서 원본 코드가 꺾이는 것을 보고 쓴 "
               f"상수 {_show(_int(rr, 'macro_argument_live'))} — 꺾임이 다른 원인일 수도 있어 이 빌드에 그 비교가 있는지는 "
               "확인되지 않았다(행 설명에 적었다)." if _int(rr, "macro_argument_live") else "")
            + (f" 점이 셋 미만(타입 끝)이라 살아 있음을 보지 않고 첫 기준 행에 둔 상수 {_show(_int(rr, 'unprobed'))}."
               if _int(rr, "unprobed") else "")
            + (f" 유효한 기준 행이 없어 행을 만들지 않은 상수 {_show(_int(rr, 'no_base'))}." if _int(rr, "no_base") else "")
            + (f" oracle 이 출력을 하나도 도출하지 못해 만들지 않은 점 {_show(_int(rr, 'underived'))}."
               if _int(rr, "underived") else "")
            + (f" 타입 폭이 선언으로 확정되지 않아(이름 패턴·기본값 추측, 타깃마다 폭이 다른 선언, 포인터) 보지 않은 입력 "
               f"{_show(_int(rr, 'inputs_type_unconfirmed'))}." if _int(rr, "inputs_type_unconfirmed") else "")
            + (f" 타입 폭을 모르는 입력(설계 범위가 있는 enum 등) {_show(_int(rr, 'inputs_no_type_width'))}."
               if _int(rr, "inputs_no_type_width") else "")
            + (f" 함수 본문을 읽지 못해 비교 상수를 찾지 않은 unit {_show(_int(rr, 'body_unread'))}."
               if _int(rr, "body_unread") else "")
            + (f" 본문의 지역 변수가 이름을 가려 보지 않은 입력 {_show(_int(rr, 'inputs_shadowed'))}."
               if _int(rr, "inputs_shadowed") else "")
            + (f" 이 빌드에서 켜질지 판정하지 못한 `#if`·`#elif` 지시문 {_show(_int(rr, 'undecided_preprocessor_blocks'))}개는 "
               "그 뒤 분기까지 읽지 않았다(꺼진 분기의 비교는 행으로 만들지 않는다)."
               if _int(rr, "undecided_preprocessor_blocks") else "")
            + (f" unit 당 상한 {_show(_int(rr, 'cap_per_unit'))}행에 잘린 점 {_show(_int(rr, 'cut'))}(상한이 비교가 살아 "
               "있는 행으로 찬 뒤의 상수는 탐침하지 않고 그 점을 모두 센다 — 이미 있는 행과 겹칠 점이 포함될 수 있다)."
               if _int(rr, "cut") else "")
            + (f" 이미 있는 행과 입력이 같아 더하지 않은 점 {_show(_int(rr, 'duplicates'))}."
               if _int(rr, "duplicates") else "")
            + (f" 선언 타입 밖이라 쓰지 않은 상수 {_show(_int(rr, 'constants_outside_type'))}."
               if _int(rr, "constants_outside_type") else "")
            + (f" 강건성 단계 오류로 행 없이 둔 unit {_show(_int(rr, 'errors'))} — 로그에 traceback 이 있다."
               if _int(rr, "errors") else ""),
            tone=_tone(bool(_int(rr, "errors")) or bool(_int(rr, "cut")))))
    out.extend(_build_assumption_item(qr.get("build_assumptions"), "suts_build_assumptions"))   # (R17)
    out.extend(_body_projection_item(qr.get("body_projection"), "suts_body_projection"))       # (R62)
    out.extend(_uds_reading_item(qr.get("uds_reading")))                                         # (R65)
    out.extend(_source_reading_item(qr.get("source_reading"), "suts_source_reading"))          # (R63)
    out.extend(_pointer_targets_item(qr.get("pointer_targets"), "suts_pointer_targets"))       # (R64)
    return out


# ── SITS ───────────────────────────────────────────────────────────────────
def _sits_items(qr: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    fc = qr.get("integration_flow_coverage")
    if not isinstance(fc, dict):
        fc = {}

    # 흐름 절단 — TC 수만 보면 "찾은 흐름 전부 시험" 으로 읽힌다. 분모는 소스에서 **찾은** 흐름 수다.
    found = _int(fc, "total_flows_found")
    if found is not None:
        emitted = _int(fc, "flows_emitted")
        dropped = _int(fc, "flows_dropped")
        # (리뷰 W2) `or 0` 는 **부재를 "제외 0" 으로 접고 "전부 실었다" 고 단정**했다 — 흐름 축을 기록하지
        #   않은 산출물이 손실 없음으로 보인다. 기록이 없으면 분모−분자로 유도하고, 그것도 못 하면
        #   "미기록" 이라고 말한다. "전부 실었다" 는 제외 수가 **확인된 0** 일 때만 쓴다.
        derived = dropped is None and emitted is not None
        if derived:
            dropped = max(0, found - emitted)
        note = "분모는 소스에서 찾은 흐름 수이고 분자는 문서에 실은 수다."
        if dropped is None:
            note += " 몇 개를 뺐는지 기록이 없다 — 전부 실었다고 읽지 말 것."
        elif dropped:
            note += " 제외된 흐름은 이 규격에 아예 없다 — max_flows 를 올리면 들어온다."
        else:
            note += " 찾은 흐름을 전부 실었다."
        out.append(_item(
            "sits_flows", "통합 흐름",
            f"{_show(emitted)} / {found}"
            + (f" (제외 {dropped}{', 유도' if derived else ''})" if dropped
               else " (제외 수 미기록)" if dropped is None else ""),
            note,
            tone=_tone(dropped is None or dropped > 0)))

    # 제외분 중 안전·설계서 등재 흐름 — 위 항목이 0 을 이미 말하므로 0 에서는 감춘다(같은 사실의 중복).
    safety_dropped = _int(fc, "dropped_safety_related_count")
    doc_dropped = _int(fc, "dropped_in_design_doc_count")
    if safety_dropped or doc_dropped:     # 둘 다 0/미기록이면 감춘다(흐름 항목이 이미 말한다)
        out.append(_item(
            "sits_dropped_critical", "제외된 흐름 중 중요한 것",
            f"안전 관련 {_show(safety_dropped)} · 설계서 등재 {_show(doc_dropped)}",
            "상한에 밀려 빠진 흐름 가운데 ASIL 이 붙었거나 설계 문서가 통합 지점으로 지목한 것이다 — "
            "상한을 올려 다시 생성할 것."
            + (f" 예: {_head(fc.get('dropped_entry_fns'))}" if fc.get("dropped_entry_fns") else ""),
            tone="warning"))

    # 호출 사슬 절단 — 흐름은 실렸는데 경로가 잘린 경우라 위 수와 다른 축이다.
    chain_cut = _int(fc, "chain_truncated_flows")
    if chain_cut:
        out.append(_item(
            "sits_chain_truncated", "잘린 호출 사슬", f"{chain_cut}개 흐름",
            f"흐름은 실렸지만 호출 경로가 노드 상한({_int(fc, 'chain_max_nodes') or '—'})에 걸려 끝까지 적히지 "
            "않았다 — 시험 절차가 경로의 앞부분만 담는다.", tone="warning"))

    # Gen Method 라벨 축 — 보강을 켰을 때만 싣는다(안 켠 문서는 말할 게 없다).
    #   ⚠ 0 도 싣는다: 켰는데 0 이면 "경계 sub-case 가 없어 라벨을 안 붙였다" 는 뜻이고,
    #     그게 곧 라벨만 바꾸지 않았다는 증거다. 켠 사실 자체는 위 공통 항목이 말한다.
    # 경계값 진단 — **Gen 칸은 안 바뀐다**. "문서가 실제로 경계를 흔들었는가" 만 말한다.
    #   키가 있으면 0 이어도 싣는다(0 은 "안 흔들었다" 는 적극적 사실이다).
    _bv = _int(fc, "flows_with_boundary_subcases")
    if _bv is not None:
        _tot = _int(qr, "total_test_cases")
        _k = _int(fc, "boundary_subcase_min_distinct")
        out.append(_item(
            "sits_boundary_subcases", "경계를 흔든 흐름",
            f"{_show(_bv)}" + (f" / {_tot}" if _tot else ""),
            f"sub-case 가 같은 입력을 {_k or '여러'}값 이상으로 바꿔 본 TC 수다. "
            "⚠ sub-case 상한에 크게 좌우된다 — 상한이 그 값보다 작으면 전부 0 이 된다. "
            "Gen Method 칸은 이 수와 무관하게 정본 짝(`REQ, IFT`↔`AOR, AEC` · `FI`↔`AOR/ABV`)을 따른다: "
            "정본마다 ABV 표기 관례가 갈려(KJPDS02 9% vs HDPDM01 99%) 유도하지 않고 수치만 보고한다."))

    # Related ID 칸 절단.
    rel_cut = _int(fc, "related_truncated_ids")
    if rel_cut:
        out.append(_item(
            "sits_related_truncated", "잘린 Related ID", f"{rel_cut}개",
            "Related ID 칸의 길이 상한에 걸려 적지 못한 ID 다 — 추적성 매트릭스에서 이 링크가 빠진다.",
            tone="warning"))

    # 관측 변수 예산 절단 — 열이 82칸뿐이라 후보를 다 못 담는다. 0 이면 감춘다(그 자체가 정상).
    cut_in = _int(fc, "var_budget_cut_input")
    cut_exp = _int(fc, "var_budget_cut_expected")
    if cut_in or cut_exp:      # 둘 다 0/미기록이면 감춘다(항목 존재 조건)
        out.append(_item(
            "sits_var_budget_cut", "예산에 잘린 관측 변수", f"입력 {_show(cut_in)} · 기대 {_show(cut_exp)}",
            "후보로 찾았지만 시트 열 예산에 걸려 관측 대상에서 뺀 변수다 — 열이 찬 것이지 후보가 없던 게 아니다.",
            tone="warning"))

    # 배열 원소 펼침 포기.
    arr_skip = _int(fc, "array_skipped_budget")
    if arr_skip:
        out.append(_item(
            "sits_array_skipped", "펼치지 못한 배열", f"{arr_skip}건",
            "정본과 같은 입도로 배열 원소를 펼치려 했지만 예산에 걸려 배열째로 뒀다 — 원소 단위 관측이 빠진다.",
            tone="warning"))

    # 링크는 있으나 전부 합성 ID 인 TC — "Related 있음" 으로 보이지만 추적 근거는 0 이다.
    synth = _int(qr, "synthetic_only_related_count")
    if synth:
        out.append(_item(
            "sits_synthetic_only", "합성 ID 뿐인 TC", f"{synth}건",
            "Related 칸은 차 있지만 전부 순번으로 만든 SwCom ID 라 설계 문서와 이어지지 않는다 — "
            "추적성 근거로 세지 말 것.", tone="warning"))

    # 근거 시트가 비었을 때 왜 비었는지.
    err = str(qr.get("strategy_sheet_error") or "").strip()
    if err:
        out.append(_item(
            "sits_strategy_error", "전략 시트 생성 실패", "실패",
            f"통합 전략 근거 시트를 만들지 못했다 — {err[:160]}", tone="warning"))

    # (R7/R9) 인터페이스 계약 — 근거로만 싣는다(시험 내용은 바꾸지 않는다). 못 읽은 파일·모호한 함수는 계약에서 빠진다.
    ic = qr.get("interface_contract")
    if isinstance(ic, dict):
        if ic.get("error"):
            out.append(_item("sits_interface_contract", "인터페이스 계약", "추출 실패",
                             f"인터페이스 계약을 읽지 못했다 — {str(ic['error'])[:160]}. 'Interface Evidence' 시트가 없다.",
                             tone="warning"))
        else:
            # (R7 리뷰 r2 W-5) 경고는 **실제로 빠진 것**이 있을 때만 — 두 번 정의된 이름이 있어도 흐름에 안 나오면 손실 0
            lost = (_int(ic, "unreadable_source_files") or 0) + (_int(ic, "ambiguous_functions") or 0)
            skipped = {k.split(":", 1)[1]: v for k, v in ic.items() if k.startswith("suggestion_skipped:") and v}
            basis = {k.split(":", 1)[1]: v for k, v in ic.items() if k.startswith("suggestion_basis:") and v}
            # (W-4) 흐름끼리 겹치므로 흐름별 합계는 같은 호출을 여러 번 센다 — 고유 수를 먼저, 합계는 괄호로
            if _int(ic, "distinct_cross_module_calls") is not None:
                value = (f"고유 모듈 경계 호출 {_show(_int(ic, 'distinct_cross_module_calls'))} · 쓰이는 반환 "
                         f"{_show(_int(ic, 'distinct_used_returns'))} · 전역 생산→소비 "
                         f"{_show(_int(ic, 'distinct_global_flows'))} (흐름별 합계 {_show(_int(ic, 'cross_module_calls'))}"
                         f" · {_show(_int(ic, 'used_returns'))} · {_show(_int(ic, 'global_flows'))})")
            else:
                value = (f"흐름별 합계 — 모듈 경계 호출 {_show(_int(ic, 'cross_module_calls'))} · 쓰이는 반환 "
                         f"{_show(_int(ic, 'used_returns'))} · 전역 생산→소비 {_show(_int(ic, 'global_flows'))}")
            _unresolved = (f"고유 {_show(_int(ic, 'distinct_unresolved_calls'))}"
                           if _int(ic, "distinct_unresolved_calls") is not None
                           else f"{_show(_int(ic, 'unresolved_calls'))}(흐름별 합계)")
            out.append(_item(
                "sits_interface_contract", "인터페이스 계약(근거)", value,
                "흐름의 모듈 경계 호출(반환 사용·비교 상수·인자 바인딩)과 모듈 간 전역 흐름을 소스에서 읽어 'Interface Evidence' "
                "시트에 실었다(둘 다 0 이면 시트가 없다). 쓰이는 반환마다 시험이 몰 수 있는 값을 '제안'으로 적었고 시험에는 적용하지 않았다(흐름의 "
                "callee 는 통합 대상이다)."
                + (" 제안 값의 근거: " + ", ".join(f"{_SITS_BASIS.get(k, k)} {v}" for k, v in sorted(basis.items()))
                   + ("." if set(basis) & _ERROR_BASES else " — 오류 비교에서 나온 값이 없어 오류 전파를 겨냥한 제안이 아니다.")
                   if basis else "")
                + (" 값을 못 정한 반환: " + ", ".join(f"{_SITS_SKIP.get(k, k)} {v}" for k, v in sorted(skipped.items()))
                   + "." if skipped else "")
                + (f" 못 읽은 소스 파일 {_show(_int(ic, 'unreadable_source_files'))} · 두 번 정의된 함수의 흐름 등장 "
                   f"{_show(_int(ic, 'ambiguous_functions'))}회는 계약에서 빠졌다." if lost else "")
                + (f" 두 번 정의된 함수 이름 {_show(_int(ic, 'duplicate_function_names'))}개는 흐름에 나오지 않는다."
                   if not _int(ic, "ambiguous_functions") and _int(ic, "duplicate_function_names") else "")
                + (f" 전처리 없이 읽어 함수로 잘못 잡힌 정의(`if` 등) {_int(ic, 'keyword_named_definitions')}개는 무시했다."
                   if _int(ic, "keyword_named_definitions") else "")
                + f" 소스에서 못 찾은 흐름 함수 {_show(_int(ic, 'missing_functions'))}회 · 이름으로 풀 수 없는 호출"
                  f"(함수 포인터·식을 거친 호출) {_unresolved}.",
                tone=_tone(bool(lost))))

    # (R16, 격차 ②) 통합 기대값 — 진입 함수를 callee 본문까지 해석해 도출한 칸. 도출이 곧 요구 적합성은 아니다.
    io = qr.get("integration_oracle")
    if isinstance(io, dict) and io.get("status"):
        status = str(io.get("status"))
        if status != "evaluated":
            out.append(_item(
                "sits_integration_oracle", "통합 기대값(소스 도출)",
                "도출 실패" if status.startswith("error") else "도출 안 함",
                f"기대값을 소스에서 도출하지 못했다({status}"
                + (f" — {str(io.get('error'))[:160]}" if io.get("error") else "")
                + ") — 모든 기대값 칸이 '[검증 필요]' 로 남는다.",
                tone="warning"))
        else:
            cells, derived = _int(io, "cells"), _int(io, "derived")
            skipped = {k: v for k, v in (io.get("tc_skipped") or {}).items() if v}
            reasons = io.get("unknown_reasons") or {}
            not_inl = io.get("not_inlined") or {}
            out.append(_item(
                "sits_integration_oracle", "통합 기대값(소스 도출)",
                f"{_show(derived)} / {_show(cells)}칸 (흐름이 쓴 값 {_show(_int(io, 'derived_assigned'))}) · 값이 있는 TC "
                f"{_show(_int(io, 'tc_with_derived'))}/{_show(_int(io, 'tc_total'))}",
                "흐름의 진입 함수를 callee 본문까지 따라 해석해(stub 이 아니라 통합된 코드) 관측 변수의 값을 도출했다 — 코드 "
                "일관성 값이지 요구 적합성·실행 결과가 아니다(하드웨어·인터럽트·다른 태스크는 모델 밖). 이 문서의 값은 생성 중 "
                "독립 경로(clang 등)로 대조하지 않았다 — scripts/integration_oracle_clang_check.py 가 생성본을 따로 잰다. "
                f"도출 칸 중 흐름이 쓴 값 {_show(_int(io, 'derived_assigned'))} · 입력을 그대로 둔 값 "
                f"{_show(_int(io, 'derived_unchanged_input'))}."
                + (" 도출 못 한 칸의 사유(상위): " + ", ".join(f"{k} {v}" for k, v in list(reasons.items())[:6])
                   + (f" 외 {int(io['unknown_reason_kinds']) - 6}종" if int(io.get("unknown_reason_kinds") or 0) > 6 else "")
                   + "." if reasons else "")
                + (" 해석하지 못해 쓰기 효과만 반영한 callee 호출: " + ", ".join(f"{k} {v}" for k, v in list(not_inl.items())[:6])
                   + (f" 외 {len(not_inl) - 6}종" if len(not_inl) > 6 else "") + "." if not_inl else "")
                + (" 도출하지 않은 TC: " + ", ".join(f"{k} {v}" for k, v in skipped.items()) + "." if skipped else "")
                + (f" 첫 sub-case 들이 모두 단계 상한을 넘은 흐름 {_int(io, 'tc_budget_cut')}개는 나머지 sub-case 를 돌리지 "
                   "않았다(칸마다 그 사유)." if _int(io, "tc_budget_cut") else ""),
                tone=_tone(bool(skipped))))

    out.extend(_build_assumption_item((qr.get("integration_oracle") or {}).get("build_assumptions"),
                                      "sits_build_assumptions"))
    out.extend(_body_projection_item((qr.get("integration_oracle") or {}).get("body_projection"),
                                     "sits_body_projection", doc="sits"))   # (R62)
    out.extend(_source_reading_item((qr.get("integration_oracle") or {}).get("source_reading"),
                                    "sits_source_reading", doc="sits"))   # (R63)
    out.extend(_pointer_targets_item((qr.get("integration_oracle") or {}).get("pointer_targets"),
                                     "sits_pointer_targets", doc="sits"))   # (R64)

    # sub-case 물량 — 흐름당 몇 갈래를 시험했나.
    sub = _int(qr, "total_sub_cases")
    if sub is not None:
        tc = _int(qr, "total_test_cases")
        out.append(_item(
            "sits_sub_cases", "sub-case", f"{sub}건" + (f" / TC {tc}" if tc is not None else ""),
            "한 통합 흐름 안에서 갈라 시험한 갈래 수다. sub-case 상한에 걸리면 갈래가 줄어든다."))
    return out


def _build_assumption_item(block: Any, key: str) -> List[Dict[str, Any]]:
    """(R17) #if 판정이 빌드 설정 증거에 기댄 정도 — 트리·빌드 어디에도 정의가 없는 이름을 0 으로 본 unit 과 그 이름."""
    if not isinstance(block, dict) or not _int(block, "units"):
        return []   # no unit had a project scope (no context, schema mismatch): nothing to say about #if verdicts
    names = [str(x) for x in (block.get("assumed_undefined_names") or [])]
    total = _int(block, "assumed_undefined_total") or 0
    reasons = block.get("incomplete_reasons") or {}
    return [_item(
        key, "빌드 설정 매크로 판정",
        f"완전한 빌드 설정 {_show(_int(block, 'units_with_complete_build_evidence'))}/{_show(_int(block, 'units'))} unit · "
        f"정의 없음으로 본 이름 {total}개",
        "빌드 설정(.cproject)의 컴파일러 옵션이 정의하는 매크로(-D)를 다 읽을 수 있으면, 트리와 빌드 어디에도 정의가 없고 구현이 "
        "정의할 수 있는 이름(밑줄로 시작·표준 라이브러리 이름)도 아닌 이름을 #if 에서 0 으로 본다(C11 6.10.1p4). 가정: 툴체인 "
        "플러그인의 기본 옵션이 -D 를 더하지 않고(파일은 기본값이 아닌 옵션만 저장한다), 컴파일러는 예약된 이름만 미리 정의하며, "
        "트리 밖 헤더(툴체인 hidef.h·stdtypes.h, <...>)와 빌드 환경(COMPOPTIONS, DEFAULT.ENV)이 이 이름들을 정의하지 않는다."
        + (" 0 으로 본 이름: " + ", ".join(names[:12]) + (f" 외 {total - 12}개" if total > 12 else "") + "." if names else "")
        + (" 빌드 설정을 증거로 쓰지 못한 unit 의 사유: " + _dist(reasons) + " — 이 unit 들은 이전처럼 미결로 둔다."
           if reasons else ""),
        tone="info")]


# (R62 review W5d) 사유마다 무엇이 채워지면 풀리는지 — 풀리지 않는 사유에 "채우면 된다" 를 붙이지 않는다
_PROJECTION_REASONS = {
    "undecided": ("판정 못 하는 #if 조건", "그 조건의 매크로 정의나 빌드 설정(-D)이 채워지면 다음 생성에서 투영된다"),
    "undecided_defined_after": ("함수보다 뒤에서(그 파일이나 뒤에 include 한 헤더에서) 정의 · 해제되는 매크로의 #if 조건",
                                "그 함수 위치의 매크로 표를 알 수 없어 투영하지 않는다 — 입력을 채워서는 풀리지 않는다"
                                "(뒤의 변경이 판정 못 하는 #if 팔 안에 있으면 그 조건이 판정될 때 다시 본다)"),
    "body_table_unknown": ("파일 수준 걷기가 따라가지 못한 매크로 표 변경이 있는 단위(걷기 밖 #define · #undef · #include, 파서가 "
                           "놓친 정의에 기대는 파일 수준 #if, 찾지 못한 include)", "그 단위의 함수 본문 #if 는 판정하지 않는다 — "
                           "입력을 채워서는 풀리지 않는다(단위별 사유는 품질 요약 table_unknown_reasons)"),
    "undecided_missed_definition": ("파일 수준 걷기가 따라가지 않는 함수 본문 안 #define(다른 곳에 정의가 없는 이름)에 기대는 #if 조건",
                                    "매크로 표가 그 정의를 모르므로 투영하지 않는다 — 입력을 채워서는 풀리지 않는다"),
    "undecided_varied": ("번역 단위 안에서 값이 바뀌는 매크로(재정의 · #undef · 함수 안 #define)의 #if 조건",
                         "그 함수 위치의 값을 알 수 없어 투영하지 않는다 — 입력을 채워서는 풀리지 않는다"),
    "undecided_reserved": ("컴파일러가 미리 정의할 수 있는 이름(밑줄로 시작 등)의 #if 조건",
                           "프로젝트 파일 · -D 만으로는 판정하지 않는다 — 대상 컴파일러가 그 이름을 정의하는지 확인이 필요하다"),
    "no_conditional_directive": ("#if 가 아닌 구문(인라인 어셈블리 · 파서가 모르는 벤더 문법 등 — @주소 · __attribute__ · "
                                 "__interrupt · __far 는 R63 부터 공백으로 읽는다)",
                                 "모델 밖 문법이라 투영으로 풀리지 않는다"),
    "conditional_compilation_unresolved": ("함수 자체가 판정 못 하는 #if 아래",
                                           "그 #if 가 판정되면(매크로 정의 · -D) 다시 본다"),
    "macro_table_changed_in_function": ("함수 안의 #define · #undef · #include", "함수 안에서 매크로 표가 바뀌어 투영하지 않는다"),
    "unbalanced": ("함수 안에서 짝이 맞지 않는 #if", "투영하지 않는다"),
    "still_error": ("투영 뒤에도 남는 다른 구문 오류", "투영으로 풀리지 않는다"),
    "function_set_changed": ("투영하면 다른 함수가 생기거나 사라짐", "투영하지 않는다"),
    "error_moved_to_another_function": ("투영하면 다른 함수에 오류가 생김", "투영하지 않는다"),
    "conflicts_with_another_projection": ("다른 함수의 투영과 함께 하면 깨짐", "투영하지 않는다"),
}


def _body_projection_item(block: Any, key: str, doc: str = "suts") -> List[Dict[str, Any]]:
    """(R62) 식 가운데를 가르는 #if 로 트리가 깨졌던 함수 — 판정된 팔만 남겨 다시 읽은 것과, 오류가 남아 읽지 못한 함수(이름 · 사유 ·
    무엇이 채워지면 풀리는지). 오류가 있던 함수가 하나도 없으면(문서 밖 함수 · 투영 예외도 없으면) 말하지 않는다."""
    if not isinstance(block, dict):
        return []
    outside = block.get("outside_document") if isinstance(block.get("outside_document"), dict) else {}
    errors = _int(block, "projection_errors") or 0
    if not _int(block, "functions_with_tree_error") and not errors and not any(outside.values()):
        return []
    projected = _int(block, "functions_projected")
    total = _int(block, "functions_with_tree_error")
    left = None if projected is None or total is None else total - projected
    reasons = block.get("not_projected") or {}
    names = [str(x) for x in (block.get("projected_functions") or [])]
    remaining = [str(x) for x in (block.get("not_projected_functions") or [])]
    remaining_total = _int(block, "not_projected_total") or len(remaining)
    assumed = [str(x) for x in (block.get("assumed_undefined") or [])]
    what_is_lost = ("그 함수의 MC/DC 결정 · 기대값은 비어 있다(칸 사유 source_parse_error, 함수 자체가 미결 #if 아래면 "
                    "conditional_compilation_unresolved)" if doc == "suts"
                    else "그 함수를 지나는 통합 기대값은 미상이다(칸 사유 source_parse_error, 함수 자체가 미결 #if 아래면 "
                    "conditional_compilation_unresolved)")
    hash_note = ("투영한 파일의 근거 해시(Test Evidence · MCDC Design · Source Findings 의 Source SHA256)는 파일이 아니라 "
                 "투영한 원문의 해시다 — "
                 "Test Evidence 의 해시 범위 열이 'captured_decoded_utf8_text_body_conditionals_projected' 로 말한다(R63: 벤더 "
                 "구문을 공백으로 읽은 파일은 '…_vendor_syntax_blanked', 값 없는 #define 뒤 공백을 옮긴 파일은 "
                 "'…_bare_define_blanks_moved' 가 함께 붙는다)."
                 if doc == "suts" else
                 "투영한 파일의 근거 해시(Test Evidence 의 Source SHA256)는 파일이 아니라 투영한 원문의 해시다.")
    return [_item(
        key, "본문 #if 투영 · 남은 파싱 오류",
        f"투영 {_show(projected)} · 남은 파싱 오류 {_show(left)} / 트리 오류 함수 {_show(total)}",
        "식 · 초기화 목록 · if 머리 한가운데의 #if/#ifdef/#else 는 C 문법 트리를 깨뜨려 그 함수 전체를 읽지 못했다(파싱 오류). "
        "그런 함수는 컴파일러가 읽는 대로 — 그 번역 단위의 매크로 표로 판정된 팔만 남기고 지시문 줄과 거짓인 팔을 같은 길이의 "
        "공백으로 지워(줄 번호 · 위치 그대로) — 다시 읽는다. 함수가 만나는 조건이 하나라도 판정되지 않거나, 함수 안에서 매크로 표가 "
        "바뀌거나, 다시 읽은 함수에 오류가 남거나, 다른 함수의 위치가 달라지면 투영하지 않고 파싱 오류로 둔다. 매크로 표는 그 단위 "
        "끝의 것이라, 단위 안에서 값이 바뀐 매크로와 함수보다 뒤에서(그 파일에서든 뒤에 include 한 헤더에서든) 정의 · 해제되는 "
        "매크로는 판정하지 않는다. " + hash_note
        + (f" 투영한 함수: {', '.join(names[:12])}" + (f" 외 {len(names) - 12}개" if len(names) > 12 else "") + "."
           if names else "")
        + (f" 판정한 조건 {_show(_int(block, 'conditions_decided'))}개." if projected else "")
        + (" 투영에서 빌드 설정 증거로 정의 없음으로 본 이름: " + ", ".join(assumed[:12]) + "." if assumed else "")
        + (" 남은 파싱 오류 — " + " · ".join(
            f"{_PROJECTION_REASONS.get(k, (k, ''))[0]} {v}"
            + (f"({_PROJECTION_REASONS[k][1]})" if k in _PROJECTION_REASONS else "") for k, v in reasons.items())
           + f". {what_is_lost}." if reasons else "")
        + (" 남은 함수: " + ", ".join(remaining[:12])
           + (f" 외 {remaining_total - 12}개" if remaining_total > 12 else "") + "." if remaining else "")
        + (f" 같은 파일의 문서에 행이 없는 함수: 투영 {outside.get('projected', 0)} · 남은 오류 "
           f"{outside.get('not_projected', 0)}(이 문서의 칸에는 영향 없음)." if any(outside.values()) else "")
        + (f" 투영 단계 예외로 원문 그대로 읽은 파일 {errors}개 — 로그를 확인할 것." if errors else "")
        + (f" 함수 본문 안에만 정의가 있어 매크로 표가 모르는 이름이 있는 단위 {_int(block, 'units_with_missed_definitions')}개(단위당 "
           f"최대 {_int(block, 'missed_definitions')}개): 그 이름에 기대는 #if 는 판정하지 않는다."
           if _int(block, "units_with_missed_definitions") else "")
        + (f" 함수 본문 등 걷기 밖의 지시문이 아는 이름을 바꿔 본문 #if 를 판정하지 않은 단위 {_int(block, 'units_table_unknown')}개."
           if _int(block, "units_table_unknown") else ""),
        tone=_tone(bool(reasons) or bool(errors)))]


_VENDOR_BLANK_LABELS = {"address_placement": "@주소 배치", "attribute": "__attribute__", "interrupt": "__interrupt",
                        "far_near": "__far · __near"}
_TEXT_CHANGE_LABELS = {"vendor_syntax_blanked": "벤더 구문 공백", "bare_define_blanks_moved": "값 없는 #define 뒤 공백 옮김",
                       "body_conditionals_projected": "본문 #if 투영"}
_PARSE_ERROR_LABELS = {
    "asm": "인라인 어셈블리(그 함수는 읽지 못한다)",
    "in_function": "함수 안(본문 #if 투영 항목이 함수별 사유를 적는다)",
    "declaration": "파일 수준의 모르는 구문(그 범위의 선언을 읽지 못했을 수 있다)",
    "missing_token": "파서가 빠진 토큰(이름 · `;` · `#endif` 등)을 채운 곳(이름 없는 `typedef enum {…};` 등 — 둘레의 구문은 읽었다)",
    "lost_structure": "파서가 닫는 괄호를 채운 곳(구조가 잘렸을 수 있다 — 매크로가 중괄호를 숨기면 그 뒤가 다른 구문으로 읽힌다)",
    "unmatched_brace": "짝 없는 중괄호(매크로가 여는 중괄호를 숨기면 그 함수가 잘려 읽힌다)",
    "cplusplus_brace": "`#ifdef __cplusplus` 안의 `extern \"C\" {` 중괄호(C 컴파일러는 보지 않는다 — 잃은 것 없음)",
    "directive": "지시문 줄(지시문은 렉서로 직접 읽어 잃은 것 없음)",
    "unnamed_bitfield": "이름 없는 비트필드 `U8 :1;`(파서 문법의 빈칸 — 비트필드 구조체는 평탄화하지 않아 잃은 것 없음)",
}


_POINTER_CAUSE_LABELS = {
    "call": "정의 없는 함수 호출(라이브러리 · 함수 포인터 변수)", "indirect_call": "주소가 넘겨진 함수(간접 호출로 무엇이든 받음)",
    "parse_error": "구문 오류가 남은 함수", "parameters_unreadable": "매개변수를 읽지 못한 정의(K&R 등)",
    "body_macro": "함수 본문이 #define 하는 이름", "opaque_macro": "본문을 읽을 수 없는 매크로(## · # · 짝 없는 괄호)",
    "macro_call": "본문이 너무 긴 매크로 호출", "macro_recursion": "되부르는 매크로", "inline_assembly": "인라인 어셈블리",
    "extra_argument": "가변 인자", "facts_missing": "흐름 사실이 없는 정의", "file_parse_error": "파일 수준 구문 오류 영역",
    "refused": "분석 거절(문맥이 읽지 못한 파일 · include · 따라갈 수 없는 저장 위치)",
    "statement_expression": "문장식 `({ … })`", "compound_literal": "복합 리터럴", "unmodeled": "모델하지 않은 식 형태",
    "lvalue": "따라갈 수 없는 대입 대상", "call_value_unmodeled": "값을 따라갈 수 없는 호출",
    "no_caller": "프로젝트 안에서 아무도 부르지 않는 함수(밖에서 무엇이든 받음)", "facts_depth": "너무 깊어 읽지 못한 식",
    "model": "따라갈 수 없는 대입 대상", "unknown_callee": "쓰기 요약이 모르는 코드에 닿음(전부 모름으로 둠)",
    "integer_write": "포인터를 담을 수 있는 객체를 바이트로 덮어씀(바이트 복사 · 다른 형식으로 겹쳐 쓰기 · 공용체)",
    "integer_to_pointer": "상수가 아닌 정수를 포인터로 바꿈", "integer_reinterpreted": "정수 저장소에서 포인터로 읽음",
    "hardware": "고정 주소 메모리에서 포인터로 읽음"}


def _pointer_targets_item(block: Any, key: str, doc: str = "suts") -> List[Dict[str, Any]]:
    """(R64) 포인터로 쓰는 callee(쓰기 요약만 쓰는 호출)와 시퀀스 stub 이 무엇을 지울 수 있나 — 프로젝트 포인터 흐름 분석으로
    대상을 특정한 함수 수와 못 한 원인. 블록이 없으면 말하지 않는다."""
    if not isinstance(block, dict) or "pointer_writers" not in block:
        return []
    writers, known = _int(block, "pointer_writers") or 0, _int(block, "known_targets") or 0
    causes = block.get("unknown_causes") if isinstance(block.get("unknown_causes"), dict) else {}
    samples = block.get("unknown_samples") if isinstance(block.get("unknown_samples"), dict) else {}
    refused = str(block.get("refused") or "")
    where = "기대값" if doc == "suts" else "통합 기대값"
    return [_item(
        key, "포인터 쓰기 대상(포인터 흐름 분석)",
        ("분석 거절 — " + refused) if refused else f"포인터로 쓰는 함수 {writers} 중 대상 특정 {known}",
        "실행 모델이 본문을 돌리지 않고 쓰기 요약으로만 다루는 callee 가 포인터로 쓰면, 이전에는 주소가 취득된 모든 객체 · 모든 "
        "배열 · 탈출한 지역 변수를 모름으로 두었다. 이제 프로젝트 전체의 포인터 흐름(읽은 모든 정의와 초기화식)으로 그 포인터가 "
        "가리킬 수 있는 객체만 모름으로 둔다 — 매개변수를 통해 쓰면 그 호출의 실인자로 푼다. 시퀀스 stub 은 본문이 없으므로 포인터를 "
        "담을 수 있는 매개변수의 실인자가 가리키는 것(과 거기서 닿는 것)만 쓸 수 있다."
        + (f" 분석이 거절되어({refused}) 이전처럼 포인터가 닿을 수 있는 모든 객체를 모름으로 둔다 — 그 파일 · include 를 읽게 하면 "
           "풀린다." if refused else
           f" 포인터로 쓰는 함수 {writers} 중 {known}개는 대상을 특정했다(그중 매개변수로 쓰는 것 "
           f"{_show(_int(block, 'through_parameters'))}개)."
           + (" 나머지는 이전처럼 모든 대상을 모름으로 둔다 — 원인: "
              + " · ".join(f"{_POINTER_CAUSE_LABELS.get(k, k)} {v}" for k, v in causes.items())
              + " (예: " + " / ".join(str(x) for k in list(causes)[:3] for x in (samples.get(k) or [])[:1]) + ")."
              if causes else ""))
        + " 가정(값이 이 가정에 기댄다): 정수 형식의 객체 · 값은 포인터를 담지 않는다(정수를 포인터로 바꾸면 하드웨어 주소 — "
          "상수(리터럴 · 열거자 · 그 매크로와 산술)를 포인터로 바꾼 것만 하드웨어로 보고, 그 밖의 정수를 포인터로 바꾼 것(캐스트 "
          "없는 변환 포함) · 정수 저장소나 고정 주소 메모리에서 포인터로 읽은 것은 어디든 가리킬 수 있다(모름) — 정수가 된 포인터가 "
          "가리키던 객체는 그런 포인터를 통해 무엇이든 저장됐을 수 있어 그 객체가 담은 포인터도 모름; 포인터를 담을 수 있는 객체를 바이트로 덮어쓰면(바이트 복사 · "
          "다른 형식으로 겹쳐 쓰기 · 공용체) 그 객체가 담은 포인터는 모름; 정수 저장소에 포인터를 넣으면(직접 · 라이브러리 복사) 그 "
          "저장소가 포인터를 담는다) · "
          "프로젝트 밖 코드는 프로젝트가 넘긴 것으로만 프로젝트 객체에 닿고, 프로젝트 함수는 넘겨진 주소나 아무도 부르지 않는 진입점으로만 "
          "부른다 · 인라인 어셈블리는 피연산자와 본문이 이름 부르는 것에만 닿는다 · 포인터 산술은 그 객체 안에 머문다."
          f" 이 분석 자체는 clang 대조가 확인하지 않는다(하네스는 오라클과 같은 대상에만 채움값을 쓴다) — {where}이 늘어난 칸은 "
          "callee 의 실제 쓰기 집합 대조로 따로 확인했다(계획서 R64 기록).",
        tone=_tone(bool(refused) or bool(causes)))]


_UDS_RANGE_UNREAD_LABELS = {
    "single_value": "값 하나(범위인지 기본값인지 문서가 말하지 않음)",
    "multiple_intervals": "여러 구간",
    "descending": "내림차순(타입 전체가 아님)",
    "signed_hex_out_of_order": "2의 보수로 읽으면 순서가 뒤집힘(다른 부호 표기 후보)",
    "signed_notation_unsigned_type": "부호 전폭 표기인데 같은 행 Type 은 부호 없음",
    "signed_notation_width_differs": "부호 전폭 표기의 폭이 같은 행 Type 과 다름",
    "ambiguous_comma": "천 단위 쉼표와 목록 쉼표가 섞임",
    "digit_count_differs": "자릿수가 다른 16진(오타 후보)",
    "outside_document_type": "같은 행 Type 이 담을 수 없는 값(오타 후보)",
    "not_a_number": "숫자가 아님",
    "hex_without_prefix": "0x 없는 16진(짝이 두 자리 이상 십진)",
    "type_in_range_column": "범위 칸에 타입 이름",
    "excludes_inner_value": "가운데 값 제외",
    "excludes_unreadable": "제외 표기를 못 읽음",
    "annotation_disagrees": "괄호 주석과 다름",
    "unread_annotation": "괄호 주석을 못 읽음",
    "no_value": "값 없음",
}
_UDS_NOTATION_LABELS = {
    "signed_hex": "부호 있는 16진(2의 보수)", "descending_full_width": "타입 전체를 `최대 ~ 최소` 로 적음",
    "array_elements": "배열 원소 범위(`array …`)", "decimal_annotation_agrees": "괄호 십진 주석으로 확인",
    "excluded_endpoint": "끝값 제외", "value_list_contiguous": "연속 값 목록(= 범위)", "trailing_comma": "끝 쉼표",
    "two_value_list": "값 둘 목록(범위가 아니라 두 값으로 읽음)",
    "hex_without_prefix": "0x 없는 16진",
}


def _uds_reading_item(block: Any) -> List[Dict[str, Any]]:
    """(R65) SwUDS 를 어떻게 읽었나 — 표시 붙은 머리말 · 표 Name 별칭 · 삭제 표시 · 세로 병합으로 이어진 행 · 이름으로 못 읽은 행 ·
    Value Range 판독(범위 · 값 목록 · 사유별 못 읽은 칸과 '고치면' 안내). SwUDS 를 주지 않았으면 말하지 않는다."""
    if not isinstance(block, dict) or not block.get("given"):
        return []
    if block.get("read_error") or not block.get("read"):
        return [_item(
            "suts_uds_reading", "SwUDS 판독(설계서를 어떻게 읽었나)", "읽지 못함",
            f"지정한 SwUDS 를 읽지 못했다({block.get('read_error') or '함수 표 0개'}) — 입력/출력 이름 · Value Range · ASIL 은 "
            "소스와 다른 문서에서 왔다. 파일 형식(.docx) · 접근을 확인할 것.", tone="warning")]
    why = block.get("range_unread_by_reason") if isinstance(block.get("range_unread_by_reason"), dict) else {}
    unit_why = block.get("unit_vars_range_unread") if isinstance(block.get("unit_vars_range_unread"), dict) else {}
    notation = block.get("range_notation") if isinstance(block.get("range_notation"), dict) else {}
    aliases = [str(x) for x in (block.get("name_row_aliases") or [])]
    marked_units = [str(x) for x in (block.get("units_via_marked_heading") or [])]
    alias_units = [str(x) for x in (block.get("units_via_name_row_alias") or [])]
    deleted = [str(x) for x in (block.get("deleted_headings") or [])]
    dropped = [str(x) for x in (block.get("alias_dropped_source") or [])]
    superseded = [str(x) for x in (block.get("superseded_headings") or [])]
    deleted_src = [str(x) for x in (block.get("deleted_in_source") or [])]
    rows_unread = [r for r in (block.get("rows_unread_samples") or []) if isinstance(r, dict)]
    unread_total = sum(int(v) for v in why.values())
    unit_unread = sum(int(v) for v in unit_why.values())
    samples = block.get("range_unread_samples") if isinstance(block.get("range_unread_samples"), dict) else {}
    return [_item(
        "suts_uds_reading", "SwUDS 판독(설계서를 어떻게 읽었나)",
        f"함수 표 {_show(_int(block, 'functions'))} · 파라미터 행 {_show(_int(block, 'param_rows'))}"
        f"(세로 병합으로 이어진 행 {_show(_int(block, 'rows_continued'))}) · Value Range 범위 {_show(_int(block, 'range_read'))}"
        f" · 값 목록 {_show(_int(block, 'values_read'))} · 못 읽음 {unread_total}",
        "SwUDS 의 설계 ID 머리말과 함수 표(입출력 파라미터 · Type · Value Range)를 한 판독기로 읽은 기록이다."
        + (f" 이름 뒤에 표시가 붙은 머리말 {_show(_int(block, 'marked_headings'))}개(예: "
           + ", ".join(f"`{x}`" for x in (block.get("marked_heading_samples") or [])[:_HEAD_N])
           + ")는 표시를 떼고 이름을 읽었다"
           + (f" — 이 문서의 unit {len(marked_units)}개가 그 표의 입출력 · 범위 · 설계 ID 를 쓴다." if marked_units else ".")
           if _int(block, "marked_headings") else "")
        + (" 머리말과 함수 표 Name 행이 다른 함수: " + "; ".join(aliases[:_HEAD_N])
           + " — 표 Name 행 이름으로도 찾는다(문서 안 불일치이므로 한쪽을 고칠 것)"
           + (f"; 그렇게 찾은 unit {len(alias_units)}개." if alias_units else ".") if aliases else "")
        + (" 표 Name 행 별칭 중 머리말 이름도 소스 함수라 쓰지 않은 것: " + ", ".join(dropped[:_HEAD_N])
           + " — 그 표가 어느 함수의 것인지 문서만으로 못 정한다." if dropped else "")
        + (f" 삭제 표시(`(삭제)`) 머리말 {len(deleted)}개는 함수의 설계로 쓰지 않았다(예: {_head(deleted)})." if deleted else "")
        + (" 같은 이름의 머리말 중 삭제 낱말이 든 것은 쓰지 않고 살아 있는 쪽을 썼다: " + "; ".join(superseded[:_HEAD_N])
           + "." if superseded else "")
        + (" 그중 소스에는 함수가 있는 것: " + ", ".join(deleted_src[:_HEAD_N])
           + " — 설계서가 지웠다고 적었으므로 SwUDS 기반 시험 범위에서 빠진다(소스와 설계서 중 한쪽을 고칠 것)."
           if deleted_src else "")
        + (f" 이름 칸을 이름으로 읽지 못한 파라미터 행 {_show(_int(block, 'rows_unread'))}개 — 예: "
           + "; ".join(f"{r.get('function')} {('입력' if r.get('section') == 'in' else '출력')} `{r.get('text')}`"
                       for r in rows_unread[:_HEAD_N])
           + ". 그 행은 입출력 목록에 없다 — 숫자로 시작하는 이름은 오타 후보라 고치면 들어가고, 식이나 문장이 든 칸은 "
           "파라미터 행이 아닐 수 있다(표 양식을 확인할 것)."
           if _int(block, "rows_unread") else "")
        + (" Value Range 를 읽지 못한 칸: " + " · ".join(
            f"{_UDS_RANGE_UNREAD_LABELS.get(k, k)} {v}" for k, v in sorted(why.items(), key=lambda kv: (-int(kv[1]), kv[0])))
           + " (예: " + "; ".join(str(s) for k in sorted(samples)[:3] for s in (samples.get(k) or [])[:1]) + ")."
           + (f" 이 문서 unit 의 변수 {unit_unread}개가 그런 칸이라 다음 출처(열거자 · HSIS · 선언 타입 폭)로 시험했다 — "
              "`lo ~ hi` 꼴로 고치면 설계 범위로 시험한다." if unit_unread else "")
           if unread_total else " Value Range 를 못 읽은 칸 없음.")
        + (f" 값 목록(`0, 5, 15`)은 열거자처럼 그 값들로 시험한다(목록 사이 정수는 쓰지 않는다) — unit 변수 "
           f"{_show(_int(block, 'unit_vars_uds_values'))}개." if _int(block, "values_read") else "")
        + (" 읽은 표기: " + " · ".join(f"{_UDS_NOTATION_LABELS.get(k, k)} {v}" for k, v in sorted(notation.items()))
           + "." if notation else ""),
        tone=_tone(bool(_int(block, "rows_unread") or aliases or unit_unread or dropped or deleted_src)))]


def _source_reading_item(block: Any, key: str, doc: str = "suts") -> List[Dict[str, Any]]:
    """(R63) 문서 함수가 읽는 C 파일(정의 파일 · include 한 헤더)을 어떻게 읽었나 — 벤더 구문을 공백으로 읽은 곳, 파서 트리가 보여
    주지 않던 파일 수준 지시문, 줄 이음을 걷고 읽은 여러 줄 매크로, 남은 구문 오류(종류별 · 모르는 선언 구문 표본), 소스 단계가
    못 읽은 파일. 범위가 붙은 unit 이 없으면(빈 블록) 말하지 않는다."""
    if not isinstance(block, dict) or not _int(block, "files_read"):
        return []
    blanks = block.get("vendor_blanks") if isinstance(block.get("vendor_blanks"), dict) else {}
    beyond = block.get("directives_beyond_tree") if isinstance(block.get("directives_beyond_tree"), dict) else {}
    errors = block.get("parse_errors") if isinstance(block.get("parse_errors"), dict) else {}
    unbalanced = block.get("unbalanced_directives") if isinstance(block.get("unbalanced_directives"), dict) else {}
    samples = [str(x) for x in (block.get("unknown_declaration_samples") or [])]
    unread = _int(block, "context_unread_files") or 0
    included = [str(x) for x in (block.get("context_unread_included") or [])]
    changes = block.get("text_change_kinds") if isinstance(block.get("text_change_kinds"), dict) else {}
    unknown_decl = _int(block, "files_with_unknown_declarations") or 0
    brace_macros = [str(x) for x in (block.get("unbalanced_brace_macros") or [])]
    lost_structure = bool(errors.get("lost_structure") or errors.get("unmatched_brace") or brace_macros)
    asm = _int(block, "files_with_asm") or 0
    lost = "그 함수의 기대값 · MC/DC 결정" if doc == "suts" else "그 함수를 지나는 통합 기대값"
    return [_item(
        key, "소스 판독(C 파일을 어떻게 읽었나)",
        f"읽은 파일 {_show(_int(block, 'files_read'))} · 벤더 구문 공백 {sum(int(v) for v in blanks.values())} · "
        f"파서 밖 지시문 {sum(int(v) for v in beyond.values())} · 모르는 선언 구문 파일 {unknown_decl}",
        "문서 함수가 읽는 C 파일(정의 파일과 include 한 헤더)을 컴파일러처럼 읽은 기록이다."
        + (" 대상 컴파일러의 문법 중 값에 영향이 없는 것은 같은 길이의 공백으로 읽어(줄 번호 · 위치 그대로) 그 선언과 함수가 읽히게 "
           "했다: " + " · ".join(f"{_VENDOR_BLANK_LABELS.get(k, k)} {v}" for k, v in blanks.items())
           + f"(파일 {_show(_int(block, 'files_with_vendor_syntax'))}개). 인라인 어셈블리는 동작이 값에 영향을 주므로 공백으로 "
           "읽지 않는다." if blanks else "")
        + (" 파서 트리가 보여 주지 않던 파일 수준 지시문(구조체 선언 안 · 인식 못 한 구문 안 · extern \"C\" 안)도 지시문 줄을 직접 "
           "읽어 매크로 표에 넣었다: " + " · ".join(f"#{k} {v}" for k, v in beyond.items())
           + f"(파일 {_show(_int(block, 'files_with_directives_beyond_tree'))}개)." if beyond else "")
        + (f" 여러 줄 매크로 {_show(_int(block, 'spliced_macro_definitions'))}개는 줄 이음(역슬래시-줄바꿈)을 걷고 읽었다."
           if _int(block, "spliced_macro_definitions") else "")
        + (" 남은 구문 오류 위치: " + " · ".join(f"{_PARSE_ERROR_LABELS.get(k, k)} {v}" for k, v in errors.items()) + "."
           if errors else " 남은 구문 오류 없음.")
        + (f" 인라인 어셈블리가 있는 파일 {asm}개 — {lost}은 비어 있을 수 있다." if asm else "")
        + (f" 모르는 파일 수준 구문이 있는 파일 {unknown_decl}개 — 예: " + " / ".join(samples[:5])
           + ". 그 범위의 선언(전역 · 타입 · 매크로가 아닌 것)은 읽지 못했을 수 있다 — 그 이름에 기대는 칸은 미상으로 남는다."
           if unknown_decl else "")
        + (" 짝이 맞지 않는 조건부 지시문: " + " · ".join(f"{k} {v}" for k, v in unbalanced.items())
           + " — 그 파일의 #if 구조는 읽은 순서대로 닫았다." if unbalanced else "")
        + (f" 소스 단계가 읽지 못한 파일(트리 전체) {unread}개(예: "
           f"{', '.join(str(x) for x in (block.get('context_unread_sample') or [])[:5])})"
           + (" — 이 문서의 함수가 include 하는 것: " + ", ".join(str(x) for x in included)
              + ". 그 파일의 선언이 필요한 식별자는 값을 확정하지 않는다(파일 접근 · 인코딩을 확인할 것)." if included
              else " — 이 문서의 함수가 include 하는 것은 없다.") if unread else "")
        + (" 소스 단계의 파일 상한(4,000)에 닿아 그 뒤 파일은 문맥에 없다." if block.get("context_file_cap_reached") else "")
        + (" @주소 배치는 지우고 읽으므로 같은 주소에 놓인 두 객체를 서로 다른 객체로 본다 — 휘발성이 아닌 객체가 주소를 "
           "공유하면 그 별칭은 모델 밖이다." if blanks.get("address_placement") else "")
        + (f" 소스 문맥에 읽지 못한 곳이 있어({block.get('alias_writes_unresolved')}) 매크로 별칭을 통한 쓰기"
           "(`#define PTADL _PTAD.…` 에 대입)를 그 객체로 풀지 않았다 — 그런 쓰기를 하는 callee 는 효과를 모르는 것으로 둔다(칸 "
           "사유 `macro_write:…`; 그 파일을 읽게 하면 풀린다)." if block.get("alias_writes_unresolved") else "")
        + (" 중괄호 짝이 맞지 않는 매크로: " + ", ".join(brace_macros[:6])
           + " — 그 매크로를 쓰는 코드는 구문 트리가 잘려 읽힐 수 있다(그 함수의 칸은 미상이거나 틀릴 수 있다)."
           if brace_macros else "")
        + (f" 읽은 원문이 파일과 달라진 정의 파일 {_show(_int(block, 'unit_files_text_changed'))}개("
           + " · ".join(f"{_TEXT_CHANGE_LABELS.get(k, k)} {v}" for k, v in changes.items())
           + ")의 근거 해시(" + ("Test Evidence · MCDC Design · Source Findings" if doc == "suts" else "Test Evidence")
           + " 의 Source SHA256)는 파일이 아니라 읽은 원문의 해시다 "
           "— 같은 길이 · 같은 줄이라 위치와 줄 번호는 파일 그대로다(Test Evidence 의 해시 범위 열이 무엇이 달라졌는지 말한다)."
           if changes else ""),
        tone=_tone(bool(unknown_decl or asm or included or unbalanced or lost_structure
                        or block.get("context_file_cap_reached"))))]


_BY_DOC_TYPE = {"sts": _sts_items, "suts": _suts_items, "sits": _sits_items}

#: 공시를 **남기는** 문서 종류 — 엔드포인트의 `expected_sidecars` 가 이 집합을 본다.
#: 손으로 든 목록을 라우터에 또 적으면 문서 종류를 늘릴 때 화면이 "이 문서 종류는 공시를
#: 만들지 않는다" 는 거짓을 적게 된다(같은 결함을 `VALIDATION_SIDECAR_WRITERS` 에서 겪었다).
DISCLOSURE_DOC_TYPES = frozenset(_BY_DOC_TYPE)


MAX_OBSERVABLE_EVALUATIONS = 2000   # generators.observable_mcdc.MAX_EVALUATIONS (공시 문구 — 테스트가 같은지 본다)
MAX_OBSERVABLE_CANDIDATES = 48      # generators.observable_mcdc.MAX_CANDIDATES


def _observable_text(mc: dict) -> str:
    """(R60) 출력 관측 MC/DC 쌍 문장 — 상태마다 그 수, 0 인 상태는 생략. 원인(결정 뒤 논리가 가림 · 미도달 · 같은 실행 안의 쌍)은
    가르지 않고, 어느 상태의 차이도 결정 탓으로 돌리지 않는다(리뷰 R60 W3 · 2차 W1·W2 · 3차 W1·W2·W5)."""
    own = mc.get("observable_searched_own_rows") if isinstance(mc.get("observable_searched_own_rows"), dict) else {}
    own_text = " · ".join(f"{label} {own[k]}" for k, label in (
        ("equal", "두 행 출력 같음"), ("underived", "두 행 도출 없음"), ("copy_only", "입력 복사만 갈림"),
        ("unreached", "두 행의 판정이 함수 실행 모델로 확인되지 않음")) if own.get(k))
    parts = [f"이미 확인됨 {_show(_int(mc, 'observable_pairs'))}"]
    for key, label in (("observable_searched", "두 조건이 확인되지 않아 탐색으로 찾은 쌍"),
                       ("observable_copy_only", "갈린 쓴 출력이 모두 움직인 입력의 복사와 같은 값(래치인지 0/1 플래그인지 가르지 못함)"),
                       ("observable_masked", "갈리는 쓴 출력을 못 찾음"),
                       ("observable_underived", "후보에서 두 행 모두 도출된 출력 없음"),
                       ("observable_recheck_refused", "행은 갈렸으나 함수 실행 모델이 쌍의 판정을 확인하지 못함(다르게 평가 · 판단 불가)"),
                       ("observable_no_candidate", "바꿀 다른 행 값이 없음"),
                       ("observable_not_checked", "확인 못 함(같은 실행 안의 쌍 · 행 값 미상 · 판정 확인 좌표 없음 · 출력 없음 · 소스 범위 없음)"),
                       ("observable_budget_exhausted", "평가 예산 소진"), ("observable_evidence_mismatch", "근거 불일치"),
                       ("observable_errors", "탐색 · 확인 실패 함수")):
        if _int(mc, key):
            parts.append(f"{label} {_show(_int(mc, key))}"
                         + (f"({own_text})" if key == "observable_searched" and own_text else ""))
    rows = _int(mc, "observable_rows")
    return (" 확장 프로파일: 유지 쌍의 두 행이 (1) 함수 실행 모델에서 쌍이 주장한 판정을 내고 (2) '쓴 출력' 에서 갈리는지 봤다 — 쓴 "
            "출력은 적어도 한 행의 실행이 썼고 두 행이 다르게 둔 입력을 그대로 옮긴 값이 아닌 출력이다(입력을 되돌려주기만 하는 출력 · "
            "래치처럼 입력을 복사한 출력은 세지 않는다; 움직인 입력에서 계산되는 출력(`cnt + 1` 등)은 센다) — " + " · ".join(parts)
            + (f" · 더한 행 {_show(rows)}" if rows else "")
            + ". 어느 상태든 그 차이를 이 결정 탓으로 돌리지 않는다(경로 증명 없음 — 조건의 연산자 결함이 드러날 필요조건이지 "
            "충분조건이 아니다). 갈리지 않는 원인은 가르지 않는다. 탐색은 결정이 의존하는 입력(식 설계: 결정식이 읽는 입력 · 함수 "
            "실행 모델 설계: 쌍의 두 행이 다른 입력)을 쌍의 값 그대로 두고 나머지를 같은 TC 의 다른 행 값으로 바꾼다(함수당 oracle "
            f"실행 {MAX_OBSERVABLE_EVALUATIONS} — 판정 확인 포함 · 쌍당 후보 {MAX_OBSERVABLE_CANDIDATES}). 실행·도달성은 대상 "
            "실행으로 검증하지 않았다. 기존 행·쌍은 바뀌지 않는다('Observable' · 'Observable Sequences' 열 — 확인 못 함은 사유를 붙인다).")


def _source_read_pass_text(mc: dict) -> str:
    """(R58) MC/DC 2차 설계(소스가 읽는 입력까지) 문장 — 채택 A · 그중 설계 D(더한 입력 거절 Dr · 그 밖 D−Dr) · 설계 못 간 채택 A−D ·
    실패 함수. 0 인 부분은 쓰지 않는다(리뷰 R58 3차 W-1: 채택했지만 설계 못 간 결정을 '거절했던 결정 0' 이라 적었다)."""
    a = _int(mc, "source_read_pass_adopted") or 0
    d = _int(mc, "source_read_pass_designed") or 0
    dr = _int(mc, "source_read_pass_designed_refused_for_added") or 0
    err = _int(mc, "source_read_pass_errors") or 0
    parts = [f"결과로 바꾼 결정 {a}"]
    if a:
        inner = []
        if dr:
            inner.append(f"기본 설계가 '더한 입력을 읽는다' 로 거절했던 결정 {dr}")
        if d - dr > 0:
            inner.append(f"다른 사유로 쌍이 없던 함수 실행 모델 결정 {d - dr}(더한 입력에 값이 생긴 실행과 2차 탐색의 새 예산 중 "
                         "무엇 덕인지는 가르지 않는다)")
        parts.append(f"그중 설계 {d}" + (": " + " · ".join(inner) if inner else ""))
        if a - d > 0:
            parts.append(f"설계까지 못 간 채택 {a - d}(부분 설계이거나 2차 설계의 사유로 바뀐 결정)")
    if err:
        parts.append(f"2차 설계 실패로 기본 설계를 유지한 함수 {err}")
    text = (f" 확장 프로파일: 소스가 읽는 입력을 더한 함수에서 기본 설계(설계서 입력 표 위)가 쌍을 하나도 못 만든 결정 "
            f"{_show(_int(mc, 'source_read_pass_decisions'))} 을 더한 입력까지 행 입력으로 써서 다시 탐색했다("
            + " · ".join(parts) + ").")
    if a:
        text += (" 그 쌍의 행은 기본 MC/DC 행 뒤에 붙고('Input Scope' = with_source_read_inputs), 기본 MC/DC 행 · 기본 설계 "
                 "결정은 바뀌지 않는다 — 다만 2차 설계 행이 새 경로를 열어 소스가 읽는 입력이 더 보이면 다음 회차에 그 함수의 "
                 "입력 열이 더해질 수 있고, 경계 · 강건성 행의 기준 행 후보가 달라질 수 있다.")
    return text + " 쌍이 하나라도 있던 결정(부분 설계)은 다시 설계하지 않는다."


def _mcdc_budget_text(budgets: Any) -> str:
    """(R56) The MC/DC path search budget the document was designed with, or nothing when the summary has none."""
    if not isinstance(budgets, list) or not budgets:
        return ""
    parts = []
    for b in budgets:
        runs, steps = (b or {}).get("max_path_runs"), (b or {}).get("max_path_steps")
        if isinstance(runs, int) and isinstance(steps, int):
            parts.append(f"벡터 {runs:,} · 인터프리터 단계 {steps:,}")
    if not parts:
        return ""
    return (" 함수 실행 모델 탐색 예산은 함수의 탐색 그룹·탐색(1차 · stub 값)마다 " + " / ".join(parts)
            + " 이다 — 결정론적 비용 상한이라 같은 소스·같은 예산은 같은 설계를 내고, 예산 안에서 못 찾은 쌍은 불가 "
            "증명이 아니다.")


def build_disclosures(doc_type: str, quality_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """`quality_report` → 화면이 그대로 그릴 공시 목록.

    Args:
        doc_type: `sts` / `suts` / `sits` (대소문자·공백 무관). 모르는 값이면 공통 항목만 나온다 —
            문서 종류를 모른다고 해서 프로파일·상한까지 감출 이유는 없다.
        quality_report: 생성기가 `<out>.payload.json` 에 남긴 dict.

    Returns:
        `{"key","label","value","note","tone"}` 목록. **키가 없는 항목은 만들지 않는다** —
        구판 산출물에 "0" 을 적으면 "손실 없음" 이라는 거짓이 된다. 값이 없으면 빈 목록이고,
        빈 목록은 "공시할 것이 없음" 이 아니라 "이 산출물이 아무것도 기록하지 않았음" 이다
        (그 구분은 호출자 — `read_generation_disclosures` — 가 `present`/`reason` 으로 말한다).
    """
    if not isinstance(quality_report, dict):
        return []
    dt = str(doc_type or "").strip().lower()
    gs = quality_report.get("generation_stats")
    items = _common_items(quality_report, gs if isinstance(gs, dict) else {})
    builder = _BY_DOC_TYPE.get(dt)
    if builder is not None:
        items.extend(builder(quality_report))
    return items
