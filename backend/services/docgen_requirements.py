"""문서 7종이 **무엇을 요구하는가** 의 단일 출처.

## 왜 필요한가

지금 생성 화면은 필수 입력이 없으면 백엔드 400 으로 죽고(`jenkins.py:3172`
``"source_root is required"``), **선택 입력이 없으면 조용히 그것 없이 만든다**
(`_resolve_opt_j`(`jenkins.py:3230`)·`_res_async_sits`(`local.py:3547`)가 파일이 없으면
`None` 을 돌려주고 그대로 진행). 후자가 더 위험하다 — 근거가 빠진 ISO 26262 산출물에
"생성 완료" 토스트가 뜬다.

이 표는 그 두 갈래를 **생성 전에** 구분해 화면에 올리기 위한 것이다.

## ⚠ 이 표는 핸들러 계약의 복제다

`required` 는 각 핸들러가 실제로 400 을 내는 조건과 **일치해야** 한다. 손으로 쓴 표라
드리프트한다. 핸들러를 고치면 여기도 고칠 것.

⚠ 이 문단은 오래 `tests/unit/test_docgen_requirements.py` 가 핸들러 소스와 대조한다고
적어 뒀는데 **그 파일은 존재한 적이 없다**(2026-08-21 실측). 지금 실재하는 대조는:

- `tests/unit/test_docgen_preflight.py::test_handlers_point_at_real_endpoints`
  — `handler` 문자열이 FastAPI 라우트 표에 실재하는가
- 같은 파일 `TestReportTemplateKeyParity` — 시험 결과 6종의 양식 키가 라우터와 같은가
- `tests/unit/test_sw_builder_form_schema_parity.py` — 빌더 폼 키가 request schema 에 있는가

`required` 목록 자체를 핸들러 소스와 자동 대조하는 검사는 **아직 없다**. 아래 주석의
줄 번호가 그 자리를 대신하고 있으므로, 핸들러를 옮기면 줄 번호도 함께 고칠 것.

## ⚠ 캡은 "부족" 이 아니라 **사용자 결정**이다

`max_tc_per_req`·`max_sequences`·`max_subcases`·`max_flows` 는 자료가 없어서가 아니라
상한 때문에 산출이 줄어드는 축이다. 조치가 "자료를 더 주세요" 가 아니라 **"상한을
올릴까요?"** 이므로 입력 결핍과 섞지 않는다.

⚠ **API 기본값이 생성기 기본값보다 작을 수 있다**(SITS `max_subcases` 7 vs 14). 버그가
아니라 의도지만(`generators/sits.py:58` 주석) 화면이 그 사실을 말해야 한다 — 사용자는
sub-case 14종 중 7종만 만들어진 걸 모른다.

## ⚠ `adjustable` 은 "핸들러가 이 이름의 Form 파라미터를 받는가" 다

`api is not None` 과 **같은 사실의 두 표현**이라 갈라지면 화면이 두 말을 한다. 그래서
`test_docgen_cap_wiring_parity.py` 가 둘의 일치를 강제하고, 프론트 전송 표
(`DocGenSection.jsx::CAP_PARAMS`)가 이 집합과 정확히 같은지도 거기서 대조한다.

조정 못 하는 캡은 **왜 못 하는지**를 반드시 갖는다 — `env`(환경변수로는 가능) 또는
`fixed`(코드 상수라 수단 없음). 둘은 사용자에게 다른 말이므로 뭉뚱그리지 않는다.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

# 입력 키 — `docgen_field_sources.INPUT_*` 와 같은 어휘를 쓰되, 문서 생성 입력에는
# 소스 루트·템플릿처럼 출처 사슬과 무관한 것도 있어 여기서 확장한다.
IN_SOURCE_ROOT = "source_root"
IN_SWRS = "swrs"
IN_SWDS = "swds"
IN_UDS_DOC = "uds_doc"
IN_HSIS = "hsis"
IN_STP = "stp"
IN_TEMPLATE = "template"
IN_VCAST = "vectorcast"
IN_SPEC_DOC = "spec_doc"        # SUTR↔SwUTS / SITR↔SwITS 대응 규격서
IN_LEVEL_ARTIFACTS = "level_artifacts"   # 통합 Summary 의 레벨별 산출물

INPUT_LABELS: Dict[str, str] = {
    IN_SOURCE_ROOT: "소스 코드 루트",
    IN_SWRS: "SwRS(요구사항)",
    IN_SWDS: "SwDS(설계서)",
    IN_UDS_DOC: "UDS 문서",
    IN_HSIS: "HSIS",
    IN_STP: "STP(시험 계획)",
    IN_TEMPLATE: "템플릿",
    IN_VCAST: "VectorCAST 결과",
    IN_SPEC_DOC: "대응 시험 규격서",
    IN_LEVEL_ARTIFACTS: "레벨별 산출물",
}


def _doc(
    *,
    label: str,
    required: List[str],
    optional: Dict[str, str],
    fields: List[str],
    caps: Dict[str, Any],
    handler: str,
    choices: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "label": label,
        "required": required,
        # 값 = **없으면 무슨 일이 생기는가**. 빈 문자열로 두지 않는다 —
        # 사유 없는 "선택 항목" 은 사용자에게 아무 정보도 주지 않는다.
        "optional": optional,
        "fields": fields,
        "caps": caps,
        # 숫자 상한이 아니라 **열거 선택**. `caps` 와 성격은 같고(자료 부족이 아니라
        # 사용자 결정) 형만 다르다. 오래 이 표가 없어서 `suts_scope` 는 화면·라우터·
        # 테스트 세 곳에 손으로 적힌 목록으로만 존재했고, 정합 가드가 그 하나를 위해
        # `_NON_CAP_PARAMS` 라는 예외 목록을 따로 들고 있었다.
        "choices": choices or {},
        "handler": handler,
    }


def _template_source_choice() -> Dict[str, Any]:
    """4개 문서가 공유하는 **템플릿 출처** 선택지.

    ⚠ 오래 이 선택 자체가 없었고 `prefer_reference=True` 가 호출부 5곳에 하드코딩돼
      있었다. 그런데 UDS 핸들러만 `reference_doc_path` 를 선언하지 않아 프론트가 보낸
      정본 경로를 FastAPI 가 조용히 버렸고, 게이트는 그 사실을 모른 채 "정본을 씁니다 /
      표준 템플릿은 쓰이지 않습니다" 라고 **반대말**을 공시했다.

    옵션 값의 철자는 `docgen_template_source.TEMPLATE_SOURCE_*` 단일 출처를 쓴다.
    """
    from backend.services.docgen_template_source import (
        TEMPLATE_SOURCE_REFERENCE,
        TEMPLATE_SOURCE_STANDARD,
    )
    return {
        "param": "template_source",
        # 준비 게이트가 이 선택을 그리는 행 id. 저장소 키·폼 키·행 id 가 셋 다 다를 수
        # 있어서(`suts_scope` → `scope` → `scope`) 표에 적어 둔다 — 안 적으면 가드가
        # 손으로 만든 대조표를 또 들고 있어야 한다.
        "row": "template_source",
        # `api: ""` = 미설정이 곧 서버 기본(정본 우선)이라는 뜻. 기본값의 정의는
        # `prefer_reference_from` 이 갖고 여기서 복제하지 않는다.
        "api": "",
        "adjustable": True,
        "options": [
            {"value": "", "label": "정본 우선 (기본)"},
            {"value": TEMPLATE_SOURCE_REFERENCE, "label": "정본 우선"},
            {"value": TEMPLATE_SOURCE_STANDARD, "label": "표준 템플릿 우선"},
        ],
        "effect": "표지·이력·Introduction(표기 규약 표)이 어디서 오는지를 정합니다 — "
                  "정본을 고르면 납품본과 같아지고 그 이력이 딸려옵니다. 명세 시트는 "
                  "어느 쪽이든 새로 씁니다.",
    }


def _suts_catalog_max(fallback: int = 30) -> int:
    """SUTS 전략 후보의 **이론적 최대**. 숫자를 여기 복제하지 않는다.

    이 값이 있어야 "전부 담으려면 얼마" 를 말할 수 있다 — `generator`(=24)는 캡이라
    그것으로 제안하면 `n <= api` 가 되어 SUTS 만 조치 제안이 영영 안 뜬다.
    """
    try:
        from generators.suts import _STRATEGY_CATALOG_MAX
        return int(_STRATEGY_CATALOG_MAX)
    except Exception:  # silent-ok: 공시는 실패해도 화면이 떠야 한다
        logging.getLogger("devops_api").debug(
            "SUTS 전략 카탈로그 최대를 생성기에서 못 읽었다 — 폴백 %s", fallback, exc_info=True)
        return fallback


def _sits_subcase_catalog_max(fallback: int = 15) -> int:
    """SITS 서브케이스 후보의 **이론적 최대**. 숫자를 여기 복제하지 않는다.

    `generator`(=`_DEFAULT_SUBCASES` 14)는 카탈로그가 아니라 **캡**이라, 그걸로 "전량" 을
    재면 `max_subcases=14` 가 손실 없음으로 판정된다 — 실제로는 15번째 후보가 잘린다.
    SUTS 가 같은 결함을 냈던 자리라 해법도 같게 둔다(`_suts_catalog_max`).
    """
    try:
        from generators.sits import _SUBCASE_CATALOG_MAX
        return int(_SUBCASE_CATALOG_MAX)
    except Exception:  # silent-ok: 공시는 실패해도 화면이 떠야 한다
        logging.getLogger("devops_api").debug(
            "SITS 서브케이스 카탈로그 최대를 생성기에서 못 읽었다 — 폴백 %s", fallback, exc_info=True)
        return fallback


def _uds_cap(name: str, fallback: int) -> int:
    """UDS 절단 상한의 **현재 유효값**. 상수를 여기 복제하지 않는다.

    `config` 는 환경변수로 덮어쓸 수 있으므로(`DEVOPS_UDS_MAX_FILES` 등) 숫자를 이
    파일에 적어 두면 화면이 실제와 다른 상한을 공시하게 된다 — 그건 공시가 없느니만
    못하다. 읽기 실패 시에만 생성기와 같은 폴백값을 쓴다.
    """
    try:
        import config as _cfg
        return int(getattr(_cfg, name, fallback))
    except Exception:  # silent-ok: 계약 조회는 실패해도 화면이 떠야 한다
        # 침묵하되 **사유를 남긴다**. config import 가 깨지면 이 폴백값이 실제 상한과
        # 다를 수 있는데, 그때 화면은 "1200개까지 읽습니다" 라고 말하면서 생성기는 다른
        # 수로 자른다. 로그가 없으면 그 어긋남을 되짚을 방법이 없다.
        logging.getLogger("devops_api").debug(
            "UDS caps 공시값을 config 에서 못 읽었다 (%s) — 폴백 %s 로 공시한다",
            name, fallback, exc_info=True,
        )
        return fallback


DOC_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "uds": _doc(
        label="UDS(단위 상세 설계)",
        # jenkins.py:2749 source_root 디렉터리 검사 · :2768 요구문서 ≥1
        required=[IN_SOURCE_ROOT, IN_SWRS],
        optional={
            IN_SWDS: "ASIL·Related·설명의 SwDS 출처가 빠지고 설계ID 매핑이 없어집니다",
            IN_TEMPLATE: "기본 양식으로 만듭니다",
        },
        fields=["asil", "related", "description"],
        # UDS 도 조용히 자른다 — sts/suts/sits 는 상한을 공시하는데 UDS 만 `caps={}` 라
        # "잘린 것이 있다" 를 화면이 말할 수 없었다. 값의 출처는 `config` 이고 실제 절단은
        # `report_gen/uds_generator.py` 의 `max_files`/`max_items` 가 한다.
        # ⚠ `api` 는 `Form(None)` 의 **실효 기본값**이라 생성기 기본과 같아야 한다
        #   (`max_flows` 와 같은 규약 — 숫자를 라우터에 복제하지 않는다).
        #   오래 `adjustable: False` 였고 요청 파라미터가 없어 환경변수로만 바꿀 수 있었다.
        # ⚠ `env` 는 이제 "유일한 수단" 이 아니라 **서버 기본값의 출처**다. 지우지 않는
        #   이유는 요청에 값을 안 실었을 때 무엇이 쓰이는지가 거기서 결정되기 때문이다.
        caps={
            "max_source_files": {
                "api": _uds_cap("UDS_MAX_SOURCE_FILES", 1200), "adjustable": True,
                "generator": _uds_cap("UDS_MAX_SOURCE_FILES", 1200),
                "env": "DEVOPS_UDS_MAX_FILES",
                "effect": "소스 파일 상한 — 넘는 파일은 **읽지 않으므로 그 안의 함수가 "
                          "문서에 아예 없습니다**. ⚠ 올리면 그만큼 느려집니다"
                          "(실측 파싱 41초/350함수 ~ 368초/750함수)",
            },
            "max_items_per_category": {
                "api": _uds_cap("UDS_MAX_FUNCTION_ITEMS", 120), "adjustable": True,
                "generator": _uds_cap("UDS_MAX_FUNCTION_ITEMS", 120),
                "env": "DEVOPS_UDS_MAX_ITEMS",
                "effect": "인터페이스/내부/매크로/타입 등 **분류별** 항목 상한 — 넘는 "
                          "항목은 규격에서 빠집니다",
            },
        },
        choices={"template_source": _template_source_choice()},
        handler="POST /api/jenkins/uds/generate-async",
    ),
    "sts": _doc(
        label="STS(SW 요구 기반 시험)",
        # jenkins.py:3171 source_root · :3221 req_texts 또는 srs_docx_path
        required=[IN_SOURCE_ROOT, IN_SWRS],
        optional={
            IN_SWDS: "시험 스텝 상세도가 낮아집니다",
            IN_UDS_DOC: "함수 설명 보강이 빠집니다",
            IN_STP: "시험 전략 문맥이 빠집니다",
            IN_TEMPLATE: "기본 양식으로 만듭니다(회사 표준 서식이 아닐 수 있습니다)",
        },
        fields=["related"],
        # ⚠ 이 상한은 **두 축**에 걸린다: 요구에 매핑된 함수 루프(`generate_test_cases`)
        #   와 함수 하나의 분기 확장(`_generate_steps_from_flow`). 오래 뒤 축만 모듈
        #   상수 5 를 직참조해서, 함수 1개짜리 요구는 상한을 올려도 5 에서 멈췄다.
        caps={"max_tc_per_req": {"api": 5, "generator": 5, "adjustable": True,
                                 "effect": "요구당 시험 케이스 상한 — 넘는 함수는 시험 없이 "
                                           "남고, 함수 하나가 내는 분기 TC 도 같은 상한에 "
                                           "잘립니다"},
              # ⚠ 오래 조정 불가였다 — `generators/sts.py:64` 의 순수 코드 상수를
              #   `:1255,1685,2525` 가 직접 참조해 env 조차 없었다. 이제 셋 다 인자로
              #   받고 `generate_test_cases` 가 `config` 에서 읽는다(`max_tc_per_req` 와
              #   같은 경로). `api` 는 `Form(None)` 의 실효 기본값이라 생성기 상수와 같다.
              "max_steps_per_tc": {"api": 15, "generator": 15,
                                   "adjustable": True,
                                   "effect": "TC 당 스텝 상한 — 넘는 스텝은 **잘려서 "
                                             "시험 절차에 남지 않습니다**(AI 보강 스텝도 "
                                             "같은 상한을 받습니다)"}},
        choices={"template_source": _template_source_choice()},
        handler="POST /api/jenkins/sts/generate-async",
    ),
    "suts": _doc(
        label="SUTS(SW 단위시험)",
        # jenkins.py:3386 source_root 만
        required=[IN_SOURCE_ROOT],
        optional={
            IN_UDS_DOC: "Related ID 보강이 빠집니다",
            IN_TEMPLATE: "기본 양식으로 만듭니다",
        },
        fields=[],
        # ⚠ `api` 는 **핸들러가 실제로 쓰는 기본값**이다(`jenkins.py:3420 Form(24)`).
        #   오래 `6` 으로 적혀 있어 화면이 `현재 6 · 생성기 기본 24` 라고 거짓 공시했다 —
        #   라우터가 6→24 로 바뀔 때 이 표만 안 따라갔다. 가드는
        #   `test_docgen_cap_wiring_parity.py::test_every_adjustable_cap_matches_handler`.
        # ⚠ `generator: 24` 는 카탈로그가 아니라 **캡**이다. 전략 후보는 함수에 따라
        #   최대 30종까지 나온다(`generators/suts._STRATEGY_CATALOG_MAX`). 오래 이 자리에
        #   "24종 중" 이라 적었는데 그건 생성기 주석의 잘못된 합(29)을 옮긴 것이었다.
        caps={"max_sequences": {"api": 24, "generator": 24, "adjustable": True,
                                "catalog_max": _suts_catalog_max(),
                                "effect": "TC 당 시험 시퀀스 수. 전략 후보는 함수에 따라 최대 "
                                          "30종(BV 6/COND 4/SWITCH 6/LOOP 3/GLOBAL 3/VOID 1/"
                                          "MC-DC 7)이고 기본값 24 는 **그 상한**입니다. "
                                          "⚠ MC/DC 가 맨 끝이라 앞에서 잘리므로, "
                                          "**switch-case 가 있는 함수는 기본값에서도 MC/DC 가 "
                                          "빠집니다**(ASIL D 는 MC/DC 필수)"}},
        # ⚠ `suts_scope` 의 저장소 키와 폼 키가 **다른 유일한 항목**이다(`scope`).
        #   오래 이 표가 없어 화면·라우터·가드가 각자 그 사실을 적어 두고 있었다.
        choices={
            "template_source": _template_source_choice(),
            "suts_scope": {
                "param": "scope",
                "row": "scope",
                # `jenkins.py:3411 Form("suds")` — 정본과 같은 범위가 기본이다.
                "api": "suds",
                "adjustable": True,
                "options": [
                    {"value": "", "label": "정본 기준 (SwUDS 설계 ID 보유 함수만)"},
                    {"value": "source", "label": "소스 전체 (SwUDS 미대조)"},
                ],
                "effect": "SwUDS 와 대조하지 않으면 정본에 없는 함수가 규격서에 "
                          "들어갑니다(실측 소스 1,160 vs 정본 1,005)",
            },
        },
        handler="POST /api/jenkins/suts/generate-async",
    ),
    "sits": _doc(
        label="SITS(SW 통합시험)",
        # local.py:3531 source_root 만
        required=[IN_SOURCE_ROOT],
        optional={
            IN_SWRS: "통합 흐름의 실 요구 ID 가 빠져 추적성이 합성 SwCom 만 남습니다",
            IN_SWDS: "Related ID 의 SwCom 축이 빕니다",
            IN_UDS_DOC: "함수 설명 보강이 빠집니다",
            IN_HSIS: "하드웨어 신호 문맥이 빠집니다",
            IN_STP: "시험 전략 문맥이 빠집니다",
            IN_TEMPLATE: "기본 양식으로 만듭니다(회사 표준 서식이 아닐 수 있습니다)",
        },
        fields=["related"],
        # ⚠ `generator: 14`(`sits._DEFAULT_SUBCASES`)는 카탈로그가 아니라 **캡**이다.
        #   후보는 BV 7/조건조합 4/에러전파 2/전역 2 = **15** 라, 14 를 "전량" 으로 재면
        #   `max_subcases=14` 가 손실 없음으로 판정되고(15번째 후보는 잘리는데) 15 를 고른
        #   사용자에겐 "14 이상은 더 담을 것이 없습니다" 라는 틀린 말이 나갔다.
        #   SUTS 의 24/30 과 같은 계열이고, 가드도 같다(`test_generator_catalog_max.py`).
        caps={"max_subcases": {"api": 7, "generator": 14, "adjustable": True,
                               "catalog_max": _sits_subcase_catalog_max(),
                               "effect": "TC 당 sub-case. 후보는 흐름에 따라 최대 15종"
                                         "(BV 7/조건조합 4/에러전파 2/전역 2)이고 생성기 "
                                         "기본값 14 는 **그 상한**입니다 — 입력 4개·전역 2개 "
                                         "이상인 흐름은 기본값에서도 한 종이 빠집니다"},
              # API 가 `max_flows` 를 받는다(미지정이면 생성기 기본값 120). 실측
              # kjpds02_pv 는 흐름 145 라 기본값으로는 25개가 규격에서 빠진다.
              "max_flows": {"api": 120, "generator": 120, "adjustable": True,
                            "effect": "통합 흐름 상한 — 넘으면 안전등급 높은 쪽부터 남기고 "
                                      "**잘린 흐름은 시험 규격에 존재하지 않습니다**"}},
        choices={"template_source": _template_source_choice()},
        handler="POST /api/local/sits/generate-async",
    ),
    # ── SwUT 3종 ────────────────────────────────────────────────────────────
    # ⚠ 커버리지의 키가 `swutcv` 가 아니라 **`swut`** 인 것은 의도다. Quality DB 가
    #   커버리지 실행을 이미 `swut` doc_type 으로 쌓아 왔고(`routers/swut.py:673`
    #   `record_run("swut", …)`), 생성 현황 보드는 그 doc_type 으로 이력을 찾는다.
    #   여기서 새 어휘를 만들면 그동안 쌓인 이력이 전부 "미생성" 으로 보인다.
    "swut": _doc(
        label="SwUTCV(단위시험 커버리지)",
        required=[IN_VCAST],
        optional={IN_SPEC_DOC: "SwUTS 규격서와 TC 대조를 못 합니다"},
        fields=[],
        caps={},
        handler="POST /api/swut/coverage/build",
    ),
    "sutr": _doc(
        label="SUTR(SW 단위시험 결과)",
        required=[IN_VCAST],
        optional={IN_SPEC_DOC: "SwUTS 규격서와 TC 대조를 못 합니다"},
        fields=[],
        caps={},
        handler="POST /api/swut/sutr/build",
    ),
    "swutcr": _doc(
        label="SwUTCR(단위시험 종합결과)",
        required=[IN_VCAST],
        optional={IN_SPEC_DOC: "SwUTS 규격서와 TC 대조를 못 합니다"},
        fields=[],
        caps={},
        handler="POST /api/swut/swutcr/build",
    ),
    # ── SwIT 3종 ────────────────────────────────────────────────────────────
    "swit": _doc(
        label="SwITCV(통합시험 커버리지)",
        required=[IN_VCAST],
        optional={IN_SPEC_DOC: "SwITS 규격서와 TC 대조를 못 합니다"},
        fields=[],
        caps={},
        handler="POST /api/swit/coverage/build",
    ),
    "sitr": _doc(
        label="SITR(SW 통합시험 결과)",
        required=[IN_VCAST],
        optional={IN_SPEC_DOC: "SwITS 규격서와 TC 대조를 못 합니다"},
        fields=[],
        caps={},
        handler="POST /api/swit/sitr/build",
    ),
    "switcr": _doc(
        label="SwITCR(통합시험 종합결과)",
        required=[IN_VCAST],
        optional={
            IN_SPEC_DOC: "SwITS 규격서와 TC 대조를 못 합니다",
            # SwITCR 만 다른 산출물을 되읽어 증적 시트를 채운다(`swit.py:_do_switcr_build`).
            # 셋 다 config fallback 이 있어 없으면 빌드가 죽는 게 아니라 **그 시트가 빈다**.
            IN_LEVEL_ARTIFACTS: "SwITCV·SwITR·Fault Injection 증적 시트가 빈 채로 나옵니다",
        },
        fields=[],
        caps={},
        handler="POST /api/swit/switcr/build",
    ),
    "swreport": _doc(
        label="통합 Summary",
        required=[IN_LEVEL_ARTIFACTS],
        optional={},
        fields=[],
        caps={},
        handler="POST /api/swreport/summary/build",
    ),
}

# 시험 결과 3종이 공통으로 요구하는 폼 필드. 프론트 `swBuilderForms.js::REQUIRED_FIELDS`
# 와 같은 목록이며, preflight 가 이 판정을 흡수해 프론트 복제를 없앤다.
TEST_REPORT_FORM_FIELDS: List[str] = ["project_id", "release_sw_version", "test_date"]

# 이 집합에 들면 preflight 가 ① `config/swut_meta.json` 의 양식 등록 여부(`report_template`
# 스텝)와 ② 위 폼 필수 3값을 검사한다. SwUT/SwIT 6종 전부 같은 검사가 필요하다 — 양식 키만
# 서로 다르고(`docgen_preflight._TEST_REPORT_TEMPLATE_KEY`), 폼은 같은 스키마를 공유한다.
TEST_REPORT_DOC_TYPES = frozenset({
    "swut", "sutr", "swutcr",
    "swit", "sitr", "switcr",
    "swreport",
})


def doc_types() -> List[str]:
    return list(DOC_REQUIREMENTS.keys())


def requirements_for(doc_type: str) -> Dict[str, Any]:
    """문서 종류의 입력 요구. 모르는 종류면 빈 계약을 준다(지어내지 않는다)."""
    return DOC_REQUIREMENTS.get(str(doc_type or "").strip().lower(), {
        "label": str(doc_type or ""), "required": [], "optional": {},
        "fields": [], "caps": {}, "choices": {}, "handler": "",
        "unknown_doc_type": True,
    })
