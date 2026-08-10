"""문서 7종이 **무엇을 요구하는가** 의 단일 출처.

## 왜 필요한가

지금 생성 화면은 필수 입력이 없으면 백엔드 400 으로 죽고(`jenkins.py:3172`
``"source_root is required"``), **선택 입력이 없으면 조용히 그것 없이 만든다**
(`_resolve_opt_j`(`jenkins.py:3230`)·`_res_async_sits`(`local.py:3547`)가 파일이 없으면
`None` 을 돌려주고 그대로 진행). 후자가 더 위험하다 — 근거가 빠진 ISO 26262 산출물에
"생성 완료" 토스트가 뜬다.

이 표는 그 두 갈래를 **생성 전에** 구분해 화면에 올리기 위한 것이다.

## ⚠ 이 표는 핸들러 계약의 복제다

`required` 는 각 `generate-async` 핸들러가 실제로 400 을 내는 조건과 **일치해야** 한다.
손으로 쓴 표라 드리프트한다 — `tests/unit/test_docgen_requirements.py` 가 핸들러 소스와
대조한다. 핸들러를 고치면 여기도 고칠 것.

## ⚠ 캡은 "부족" 이 아니라 **사용자 결정**이다

`max_tc_per_req`·`max_sequences`·`max_subcases`·`max_flows` 는 자료가 없어서가 아니라
상한 때문에 산출이 줄어드는 축이다. 조치가 "자료를 더 주세요" 가 아니라 **"상한을
올릴까요?"** 이므로 입력 결핍과 섞지 않는다.

⚠ **API 기본값이 생성기 기본값보다 작다**(SUTS 6 vs 24, SITS 7 vs 14). 버그가 아니라
의도지만(`generators/sits.py:58` 주석) **화면이 그 사실을 말한 적이 없다** — 사용자는
전략 24종 중 6종만 만들어진 걸 모른다.
"""
from __future__ import annotations

from typing import Any, Dict, List

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
) -> Dict[str, Any]:
    return {
        "label": label,
        "required": required,
        # 값 = **없으면 무슨 일이 생기는가**. 빈 문자열로 두지 않는다 —
        # 사유 없는 "선택 항목" 은 사용자에게 아무 정보도 주지 않는다.
        "optional": optional,
        "fields": fields,
        "caps": caps,
        "handler": handler,
    }


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
        caps={},
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
        },
        fields=["related"],
        caps={"max_tc_per_req": {"api": 5, "generator": 5,
                                 "effect": "요구당 시험 케이스 상한 — 넘는 함수는 시험 없이 남습니다"},
              "max_steps_per_tc": {"api": None, "generator": 15,
                                   "effect": "TC 당 스텝 상한"}},
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
        caps={"max_sequences": {"api": 6, "generator": 24,
                                "effect": "TC 당 시험 시퀀스 수 — 생성기 기본 24종(BV/COND/SWITCH/"
                                          "LOOP/GLOBAL/VOID/MC-DC) 중 이 수만큼만 만듭니다"}},
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
        },
        fields=["related"],
        caps={"max_subcases": {"api": 7, "generator": 14,
                               "effect": "TC 당 sub-case — 생성기 기본 14종(BV 7/조건조합 4/"
                                         "에러전파 2/전역 2) 중 이 수만큼만 만듭니다"},
              # API 가 `max_flows` 를 받는다(미지정이면 생성기 기본값 120). 실측
              # kjpds02_pv 는 흐름 145 라 기본값으로는 25개가 규격에서 빠진다.
              "max_flows": {"api": 120, "generator": 120, "adjustable": True,
                            "effect": "통합 흐름 상한 — 넘으면 안전등급 높은 쪽부터 남기고 "
                                      "**잘린 흐름은 시험 규격에 존재하지 않습니다**"}},
        handler="POST /api/local/sits/generate-async",
    ),
    "sutr": _doc(
        label="SUTR(SW 단위시험 결과)",
        required=[IN_VCAST],
        optional={IN_SPEC_DOC: "SwUTS 규격서와 TC 대조를 못 합니다"},
        fields=[],
        caps={},
        handler="POST /api/swut/sutr/build",
    ),
    "sitr": _doc(
        label="SITR(SW 통합시험 결과)",
        required=[IN_VCAST],
        optional={IN_SPEC_DOC: "SwITS 규격서와 TC 대조를 못 합니다"},
        fields=[],
        caps={},
        handler="POST /api/swit/sitr/build",
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

TEST_REPORT_DOC_TYPES = frozenset({"sutr", "sitr", "swreport"})


def doc_types() -> List[str]:
    return list(DOC_REQUIREMENTS.keys())


def requirements_for(doc_type: str) -> Dict[str, Any]:
    """문서 종류의 입력 요구. 모르는 종류면 빈 계약을 준다(지어내지 않는다)."""
    return DOC_REQUIREMENTS.get(str(doc_type or "").strip().lower(), {
        "label": str(doc_type or ""), "required": [], "optional": {},
        "fields": [], "caps": {}, "handler": "",
        "unknown_doc_type": True,
    })
