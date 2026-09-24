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
        skipped = {k.split(":", 1)[1]: v for k, v in rb.items() if k.startswith("skipped:") and v}
        _why = {"kind_symbolic": "기호 비교(값 미상)", "kind_range": "범위", "not_an_order_comparison": "순서 비교 아님",
                "no_subject_for_value": "주어 없음", "response_constraint": "응답 제약(측정 대상)",
                "negated_condition": "부정 절", "same_subject_combination_unstated": "결합 미기재",
                "monitored_quantity_unknown": "감시량 미상", "duplicate_fact": "중복", "outcome_section": "출력·완료 조건",
                "reference_label": "기준값 라벨", "value_outside_subject_type": "변수 폭 밖의 값"}

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
               "('F() return')으로 stub 한 시퀀스에서 나왔다 — 시험도 그 함수를 stub 해야 성립한다(시퀀스 단위로 센 상한)."
               if _int(ev, "derived_in_stubbed_sequence") else "")))

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
            + (f" 결정을 나열하지 못한 함수 {_show(_int(mc, 'unenumerated_functions'))} · 분석하지 못한 unit "
               f"{_show(_int(mc, 'units_not_analyzed'))} 는 위 분모 밖이다."
               if (_int(mc, "unenumerated_functions") or _int(mc, "units_not_analyzed")) else "")
            + " 결정별 근거는 'MCDC Design' 시트에 있다.",
            tone=_tone(bool(_int(mc, "invalidated_pairs")))))

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
            "uds_range=설계서가 적은 값 범위 · enum=열거자 값 집합 · hsis=HSIS 범위 · type=선언 타입의 전폭 · "
            "unknown=비운 칸. type 비중이 크면 값은 유효하지만 설계 의도가 아니라 타입이 정한 경계다."))

    # 설계서 범위와 선언 타입이 어긋난 변수 — 문서 쪽 오류일 수 있어 사람이 봐야 한다.
    conflicts = _int(qr, "range_conflict_count")
    if conflicts is not None:
        note = "설계서가 적은 값 범위가 선언 타입의 폭을 벗어난 변수다."
        if conflicts:
            head = _head(qr.get("range_conflicts"))
            note += f" 예: {head}" if head else ""
            note += " — 설계서와 소스 중 한쪽이 틀렸다는 뜻이라 값을 고르지 않고 타입 폭으로 시험했다."
        else:
            note += " 어긋난 변수가 없다 — 설계서 범위와 선언 타입이 서로 맞는다."
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

    # sub-case 물량 — 흐름당 몇 갈래를 시험했나.
    sub = _int(qr, "total_sub_cases")
    if sub is not None:
        tc = _int(qr, "total_test_cases")
        out.append(_item(
            "sits_sub_cases", "sub-case", f"{sub}건" + (f" / TC {tc}" if tc is not None else ""),
            "한 통합 흐름 안에서 갈라 시험한 갈래 수다. sub-case 상한에 걸리면 갈래가 줄어든다."))
    return out


_BY_DOC_TYPE = {"sts": _sts_items, "suts": _suts_items, "sits": _sits_items}

#: 공시를 **남기는** 문서 종류 — 엔드포인트의 `expected_sidecars` 가 이 집합을 본다.
#: 손으로 든 목록을 라우터에 또 적으면 문서 종류를 늘릴 때 화면이 "이 문서 종류는 공시를
#: 만들지 않는다" 는 거짓을 적게 된다(같은 결함을 `VALIDATION_SIDECAR_WRITERS` 에서 겪었다).
DISCLOSURE_DOC_TYPES = frozenset(_BY_DOC_TYPE)


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
