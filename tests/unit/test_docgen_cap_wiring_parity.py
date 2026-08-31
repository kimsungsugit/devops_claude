"""준비 게이트 상한의 3자 정합 — 공시표 ↔ 실제 핸들러 ↔ 프론트 전송표.

## 왜 필요한가

`docgen_requirements.DOC_REQUIREMENTS` 의 `caps` 는 **핸들러 계약의 손 복제**다(그 모듈
docstring 이 스스로 경고한다). 실제로 SUTS `max_sequences` 는 라우터가 6 → 24 로 바뀔 때
이 표만 따라가지 않아, 화면이 오래 `현재 6 · 생성기 기본 24` 라고 **거짓 공시**했다.

프론트 전송표(`DocGenSection.jsx::CAP_PARAMS`)도 같은 복제다. 갈라지면 둘 중 하나다:

- 게이트가 입력칸을 그리는데 값이 요청에 안 실린다 = **거짓 통제**. 사용자는 고쳤다고
  믿는데 문서는 그대로다. STS `max_tc_per_req` 가 실제로 이 상태였다.
- 서버가 받지 않는 키를 보낸다 = 죽은 코드. FastAPI 는 미선언 Form 필드를 **조용히
  무시**하므로 실서비스에서는 절대 드러나지 않는다.

## 왜 프로덕션 코드가 아니라 테스트가 대조하나

`DOC_REQUIREMENTS` 는 모듈 로드 시 평가되는 dict 리터럴이라, 그 안에서 라우트 표를 뒤지면
`backend.main` → `routers.docgen_preflight` → `services.docgen_requirements` → `backend.main`
순환이 **import 시점에** 확정된다(lazy import 로도 못 피한다). 그래서 이 저장소의 기존
관례를 따른다 — `test_sw_builder_form_schema_parity.py` 가 폼(JS) ↔ Pydantic 스키마를
대조하듯, 여기서는 테스트가 라우트 표와 JSX 를 읽는다.
"""
from __future__ import annotations

import inspect
import pathlib
import re
from typing import Any, Dict

import pytest

from backend.services import docgen_requirements as req

_REPO = pathlib.Path(__file__).resolve().parents[2]
_SECTION_JSX = _REPO / "frontend-v2" / "src" / "components" / "sections" / "DocGenSection.jsx"

def _choices(doc_type: str) -> Dict[str, Dict[str, Any]]:
    """숫자 상한이 아닌 **열거 선택**(`docgen_requirements` 의 `choices` 표).

    ⚠ 예전엔 여기에 `_NON_CAP_PARAMS = {"suts_scope": ("suts", "scope")}` 라는 **손으로
      적은 예외 목록**이 있었다. 그 목록이 곧 "표 밖에 통제가 하나 더 있다" 는 뜻이었고,
      실제로 그 밖에서 만든 통제(`template_source`)가 UDS 에서 통째로 거짓이었다.
      이제 계약이 표에 있으므로 가드는 표를 읽는다 — 새 선택지를 추가해도 자동으로 덮인다.
    """
    return req.requirements_for(doc_type).get("choices") or {}


def _form_default(handler: str, param: str) -> Any:
    """`"POST /api/x"` 핸들러의 `param` Form 기본값.

    파라미터가 없으면 ``KeyError`` — 그 자체가 "핸들러가 이 값을 안 받는다" 는 판정이다.
    """
    from backend.main import app

    for route in app.routes:
        for method in getattr(route, "methods", None) or ():
            if f"{method} {route.path}" != handler:
                continue
            p = inspect.signature(route.endpoint).parameters[param]
            # `Form(5)` 는 `fastapi.params.Form` 인스턴스이고 실제 기본값은 `.default` 다.
            return getattr(p.default, "default", p.default)
    raise AssertionError(f"{handler}: 그런 라우트가 없다")


def _cap_params() -> Dict[str, Dict[str, str]]:
    """`DocGenSection.jsx` 의 `CAP_PARAMS` → `{doc_type: {저장소키: 폼키}}`."""
    src = _SECTION_JSX.read_text(encoding="utf-8")
    m = re.search(r"const CAP_PARAMS = \{(.*?)\n\};", src, re.S)
    assert m, "CAP_PARAMS 를 못 찾았다 — 상수 이름이 바뀌었으면 이 테스트도 따라가야 한다"
    out: Dict[str, Dict[str, str]] = {}
    for doc_type, block in re.findall(r"(\w+):\s*\{([^}]*)\}", m.group(1)):
        out[doc_type] = dict(re.findall(r"(\w+):\s*'([a-z_]+)'", block))
    return out


def test_every_adjustable_cap_matches_handler() -> None:
    """조정 가능하다고 공시한 상한은 핸들러가 **그 이름으로 실제로 받아야** 한다.

    이름이 틀리면 `KeyError` 로 죽는다 — 그게 `adjustable` 의 정의 그 자체다.
    """
    for doc_type in req.doc_types():
        spec = req.requirements_for(doc_type)
        for name, cap in (spec.get("caps") or {}).items():
            if not cap.get("adjustable"):
                continue
            got = _form_default(spec["handler"], name)
            if got is None:
                # `Form(None)` = 미지정이면 생성기 기본값을 쓴다는 뜻이다(SITS max_flows).
                # 그럴 때 공시값은 **생성기 기본값**이어야 화면이 실효 상한을 말한다.
                assert cap["api"] == cap["generator"], (
                    f"{doc_type}/{name}: 핸들러가 Form(None) 이라 실효 기본값은 생성기 "
                    f"기본 {cap['generator']} 인데 공시는 {cap['api']} 다"
                )
            else:
                assert got == cap["api"], (
                    f"{doc_type}/{name}: 공시 {cap['api']} ≠ 핸들러 기본값 {got} "
                    f"({spec['handler']})"
                )


def test_unadjustable_caps_have_no_handler_param_and_say_why() -> None:
    """조정 불가라고 공시했으면 핸들러에 **정말 없어야** 하고, 사유가 있어야 한다.

    이 단언이 없으면 "전부 False 로 바꿔라" 뮤턴트가 살아남아, 이번에 고친 STS/SUTS 가
    조용히 죽은 입력칸으로 되돌아간다.
    """
    for doc_type in req.doc_types():
        spec = req.requirements_for(doc_type)
        for name, cap in (spec.get("caps") or {}).items():
            if cap.get("adjustable"):
                continue
            with pytest.raises((KeyError, AssertionError)):
                _form_default(spec["handler"], name)
            # env(환경변수로는 가능)와 fixed(코드 상수라 수단 없음)는 **사용자에게 다른
            # 말**이다. 없으면 화면이 사유 없는 비활성을 그리고, 그건 고장으로 읽힌다.
            assert cap.get("env") or cap.get("fixed"), (
                f"{doc_type}/{name}: 왜 못 바꾸는지가 없다"
            )


def test_adjustable_flag_and_api_default_cannot_disagree() -> None:
    """`adjustable` 과 `api is not None` 은 **같은 사실의 두 표현**이다.

    두 벌이 갈라지면 화면이 두 말을 한다 — 이 저장소가 반복해서 밟은 결함이라 못박는다.
    """
    for doc_type in req.doc_types():
        for name, cap in (req.requirements_for(doc_type).get("caps") or {}).items():
            assert bool(cap.get("adjustable")) is (cap.get("api") is not None), (
                f"{doc_type}/{name}: adjustable={cap.get('adjustable')} 인데 "
                f"api={cap.get('api')}"
            )


@pytest.mark.parametrize("doc_type", ["uds", "sts", "suts", "sits"])
def test_frontend_sends_exactly_the_adjustable_caps(doc_type: str) -> None:
    """화면이 조정하게 해 놓고 안 보내면 **거짓 통제**, 안 받는 걸 보내면 죽은 코드다."""
    caps = req.requirements_for(doc_type).get("caps") or {}
    choices = _choices(doc_type)
    expected = ({n for n, c in caps.items() if c.get("adjustable")}
                | {n for n, c in choices.items() if c.get("adjustable")})
    sent = _cap_params().get(doc_type, {})
    assert set(sent) == expected, (
        f"{doc_type}: 프론트 전송표와 조정 가능 항목이 다르다"
    )
    # 상한은 저장소 키와 폼 키가 같아야 한다 — 다르면 서버가 조용히 무시한다.
    # 선택지는 다를 수 있으나(`suts_scope` → `scope`) **표가 정한 이름**이어야 한다.
    for store_key, form_key in sent.items():
        want = (choices[store_key]["param"] if store_key in choices else store_key)
        assert form_key == want, (
            f"{doc_type}/{store_key}: 폼 키가 {form_key} 인데 계약은 {want} 다")


@pytest.mark.parametrize("doc_type", ["uds", "sts", "suts", "sits"])
def test_every_adjustable_choice_matches_handler(doc_type: str) -> None:
    """선택지도 상한과 같은 3자 정합을 받는다 — 핸들러가 그 이름으로 실제로 받는가.

    `template_source` 가 이 검사 없이 들어왔다면 UDS 에서 또 조용히 버려졌을 것이다.
    """
    spec = req.requirements_for(doc_type)
    for name, ch in _choices(doc_type).items():
        if not ch.get("adjustable"):
            continue
        got = _form_default(spec["handler"], ch["param"])
        assert got == ch["api"], (
            f"{doc_type}/{name}: 공시 {ch['api']!r} ≠ 핸들러 기본값 {got!r} "
            f"({spec['handler']})")
        # 옵션에 기본값(빈 값)이 없으면 화면이 "서버 기본으로 되돌리기" 를 못 제공한다.
        assert any(o.get("value") == "" for o in ch.get("options") or []), (
            f"{doc_type}/{name}: 미설정으로 되돌릴 선택지가 없다")


def test_cap_names_are_globally_unique() -> None:
    """프론트 저장소(`devops_v2_docgen_caps`)가 **평면**이라 이름이 겹치면 두 문서가 같은
    값을 조용히 공유한다. 화면은 그 사실을 말할 수 없으므로 겹치기 전에 막는다.
    """
    seen: Dict[str, str] = {}
    for doc_type in req.doc_types():
        for name in req.requirements_for(doc_type).get("caps") or {}:
            assert name not in seen, f"{name}: {seen[name]} 와 {doc_type} 가 같은 이름을 쓴다"
            seen[name] = doc_type


# ── 게이트가 내는 통제 ↔ 핸들러가 받는 값 (2026-08-31) ──────────────────────
#
# 위 세 검사는 `caps` 표만 봤다. 그래서 **표 밖에서 통제를 하나 더 만들었을 때** 아무도
# 못 막았다: `asil_level` 결정 행을 UDS 를 포함한 4종에 냈는데, UDS 핸들러는 그 파라미터를
# 선언하지 않는다. 프론트가 보내도 FastAPI 가 **조용히 버리고**, 화면은 선택기를 그린 채
# 초록이 된다 — 사용자는 ASIL D 를 골랐다고 믿고 문서는 등급 없이 나간다.
#
# 그래서 대조 대상을 "게이트가 실제로 내는 decision 행" 으로 넓힌다. `caps` 로 만들어진
# 행은 위에서 이미 보므로, 여기서는 **손으로 추가한 결정 행**을 겨눈다.

# 게이트가 `caps` 표 없이 직접 만드는 결정 행 → 그 값을 받아야 하는 폼 파라미터 이름.
# 폼 파라미터를 요구하지 않는 행(순수 공시·화면 전용)은 `None` 으로 둔다.
_HANDMADE_DECISION_PARAM = {
    "asil_level": "asil_level",
}


def _decision_param_for(doc_type: str, row_id: str):
    """행 id → 그 값을 받아야 하는 폼 파라미터. 없으면 `None`(순수 공시 행).

    선택지 행은 **`choices` 표가 스스로 밝힌다**(`row`/`param`). 손 목록에는 표 밖에서
    만든 행만 남는다 — 목록이 길어지면 그만큼 계약 밖 통제가 늘었다는 뜻이다.
    """
    for ch in _choices(doc_type).values():
        if ch.get("row") == row_id:
            return ch.get("param")
    return _HANDMADE_DECISION_PARAM.get(row_id)


def _decision_rows(doc_type: str, **kw) -> Dict[str, Dict[str, Any]]:
    """게이트가 이 문서에 내는 decision 단계 행 (`cap_*` 제외)."""
    from backend.routers.docgen_preflight import PreflightRequest, _compute_preflight

    out = _compute_preflight(PreflightRequest(doc_type=doc_type, source_root="", **kw))
    return {s["id"]: s for s in out["steps"]
            if s.get("phase") == "decision" and not str(s["id"]).startswith("cap_")}


@pytest.mark.parametrize("doc_type", ["uds", "sts", "suts", "sits"])
def test_every_handmade_decision_row_reaches_its_handler(doc_type: str) -> None:
    """게이트가 통제를 그리면 그 값을 **핸들러가 실제로 받아야** 한다.

    받지 않으면 거짓 통제다 — FastAPI 는 미선언 Form 필드를 조용히 무시하므로
    실서비스에서는 초록 화면과 바뀌지 않은 문서로만 나타난다.
    """
    handler = req.DOC_REQUIREMENTS[doc_type]["handler"]
    for row_id in _decision_rows(doc_type):
        param = _decision_param_for(doc_type, row_id)
        if param is None:
            continue      # 폼 값을 요구하지 않는 행(순수 공시)
        try:
            _form_default(handler, param)
        except KeyError:
            raise AssertionError(
                f"{doc_type}: 게이트가 `{row_id}` 통제를 내는데 {handler} 는 "
                f"`{param}` 을 받지 않는다 — 고른 값이 조용히 버려진다(거짓 통제)"
            ) from None


def test_uds_has_no_asil_control() -> None:
    """UDS 는 ASIL 결정 행을 내지 않는다 — 음성 대조군.

    UDS 의 ASIL 은 **함수별 증거**에서 온다(`uds_generator:1408` Doxygen `@asil` →
    SwDS 맵 → 없으면 `TBD`, 출처는 `asil_source`). 프로젝트 기본값을 주입하면 정직한
    `TBD` 전체를 지어낸 등급으로 덮는다. 그 표면은 이미 `chain_asil` 행이 맡는다.
    """
    assert "asil_level" not in _decision_rows("uds")
    assert "asil_level" in _decision_rows("sts"), "반대로 STS 에서 사라지면 배선이 죽은 것"


def test_frontend_does_not_send_asil_for_uds() -> None:
    """전송 쪽도 같아야 한다 — 보내 봐야 버려지는 죽은 코드이고, 두 곳이 갈리면
    다음 사람이 어느 쪽이 옳은지 알 수 없다."""
    src = _SECTION_JSX.read_text(encoding="utf-8")
    m = re.search(r"const _asil = (.*?);", src, re.S)
    assert m, "_asil 계산부를 못 찾았다"
    assert "uds" in m.group(1), f"UDS 예외가 없다: {m.group(1)!r}"


# ── 게이트와 생성이 **같은 대상**을 보는가 ────────────────────────────────────
_BOARD_JSX = _REPO / "frontend-v2" / "src" / "components" / "sections" / "DocGenStatusBoard.jsx"
_API_JS = _REPO / "frontend-v2" / "src" / "api.js"


class TestGateAndGenerationSeeTheSameTarget:
    """게이트가 판정한 것과 생성이 쓰는 것이 갈리면, 게이트는 조용히 **다른 문서** 얘기를 한다.

    실측 결함: 게이트는 `cache_root` 를 `analysisResult?.cacheRoot || ''` 로만 보냈고
    생성 요청은 세 단계 폴백을 탔다. 빈 문자열이면 백엔드가 `~/.devops_pro_cache` 로
    떨어져(`backend/helpers/jenkins.py:_normalize_jenkins_cache_root`) 화면이 쓰는
    `.devops_pro_cache/<user>` 와 다른 폴더를 본다 → UDS 빌드 캐시를 "없음(진행 불가)"
    으로 보고하면서 정작 생성은 성공한다.

    행동 축은 vitest 가 본다(요청 본문의 실제 값). 여기서는 **구조 축**을 본다 —
    누군가 폴백을 다시 손으로 적으면 두 벌이 되고, 그 순간 값이 갈릴 수 있다.
    """

    def test_cache_root_fallback_lives_in_one_place(self) -> None:
        assert "export function resolveCacheRoot(" in _API_JS.read_text(encoding="utf-8"), \
            "폴백 사슬의 단일 출처가 사라졌다"

    @pytest.mark.parametrize("path", [_SECTION_JSX, _BOARD_JSX])
    def test_docgen_surfaces_use_the_shared_resolver(self, path: pathlib.Path) -> None:
        src = path.read_text(encoding="utf-8")
        assert "resolveCacheRoot(" in src, f"{path.name} 이 공용 해석기를 쓰지 않는다"
        # 주석은 이 결함을 **설명**하므로 코드 라인만 본다.
        code = [ln for ln in src.splitlines()
                if not ln.lstrip().startswith(("//", "*", "/*"))]
        offenders = [ln.strip() for ln in code
                     if re.search(r"analysisResult\?\.cacheRoot\s*\|\|", ln)]
        assert not offenders, (
            f"{path.name} 이 폴백을 손으로 다시 적었다 — 두 벌이 되면 값이 갈린다: {offenders}")


class TestGenerationRefusesAmbiguousProject:
    """생성 경로가 **임의의 SCM 항목을 집지 않는다**.

    `DocGenSection.jsx` 의 주석은 오래 "falling back to scmList[0] would silently generate
    docs against the wrong project" 라고 경고하면서 바로 아래에서 그 일을 했다. 실측:
    이 저장소 레지스트리엔 프로젝트가 3개 있어, 매칭이 없으면 항상 첫 항목으로 만들었다.

    행동 축(요청이 안 나간다)은 vitest 가 본다. 여기서는 **그 표현이 다시 들어오지 않는지**
    를 본다 — 되살아나면 화면상 아무 증상이 없고, 문서 내용만 조용히 남의 것이 된다.
    """

    # 같은 폴백이 `docGenHelpers.useScmFallback` 에도 있었다 — 한쪽만 고치면 '문서 현황'
    # 표와 `registerVcast`(남의 `source_root` 로 패키지 등록)가 그대로 남는다.
    @pytest.mark.parametrize("path", [
        _SECTION_JSX,
        _REPO / "frontend-v2" / "src" / "docGenHelpers.js",
    ])
    def test_no_unconditional_first_entry_pick(self, path: pathlib.Path) -> None:
        src = path.read_text(encoding="utf-8")
        code = [ln for ln in src.splitlines()
                if not ln.lstrip().startswith(("//", "*", "/*"))]
        # ⚠ `items[0]` 만으로 잡으면 무관한 자리(VectorCAST 패키지 목록의 첫 항목)까지
        #   걸린다. **SCM 후보를 집는 자리**만 본다.
        bad = [ln.strip() for ln in code
               if re.search(r"scmList\s*\??\.?\[0\]", ln)
               or re.search(r"(?:setScm\(|scm\s*=\s*)items\[0\]", ln)]
        assert not bad, f"무조건 첫 SCM 을 집는 코드가 되살아났다: {bad}"
        assert "soleScmEntry" in src, "후보가 하나일 때만 고르는 판정이 사라졌다"

    def test_generation_checks_provenance_before_sending(self) -> None:
        """산출물을 만드는 쪽에도 출처 가드가 있어야 한다(읽기 화면 4곳엔 이미 있다)."""
        src = _SECTION_JSX.read_text(encoding="utf-8")
        assert "contextConflict(" in src, \
            "생성 경로가 analysisResult ↔ job 대조 없이 요청을 보낸다"
