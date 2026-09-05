"""C 함수가 **반환값을 가지는가** — 판정 단일 출처.

## 왜 별도 모듈인가

이 판정이 프로덕션 **7곳**에 복제돼 있었고, 규칙이 **3가지**로 갈려 있었다
(2026-08-26 실측):

======================================  ==========================  =========
사이트                                   규칙                        판정
======================================  ==========================  =========
``backend/helpers/common.py``            ``ret.lower() != "void"``   정확일치
``generators/suts.py`` (출력변수)         ``ret.lower() != "void"``   정확일치
``backend/services/docgen_test_``        ``t.lower() != "void"``     정확일치
``materials.py``
``generators/suts.py`` (경량파서)         ``"void" not in .lower()``  부분문자열
``report_gen/function_analyzer.py``      ``"void" not in head``      부분문자열
``report_gen/uds_generator.py``          ``"void" not in rt``        부분문자열
``generators/suts.py`` (RETURN_CHECK)    ``"void" in proto[:"("]``   부분문자열
======================================  ==========================  =========

같은 소스에서 두 무리가 **반대 답**을 냈다. PDS64_RD 실측: 선언 654건 중 15건
(고유 타입 2개 — ``__interruptvoid`` 14 · ``__EXTERN_C void`` 1)에서 갈렸다.

## 두 규칙 다 틀렸다

* **정확일치** — ``__interrupt void`` 는 ``"void"`` 와 다르므로 "반환값 있음"이 된다.
  실제 산출물(`uds_local_20260825_153411.docx`)에 그 결과가 실렸다:
  ``Prototype`` 12칸 + Output Parameters 그리드 12행이 ``return __interruptvoid``
  (+ ``Calling Function`` 10칸, 합 34회). **void 인터럽트 핸들러가 설계서에서
  반환값을 가진 함수로 적혀 있었다.**
* **부분문자열** — ``void *`` 를 반환값 없음으로 막는다. 이 소스엔 void 포인터를
  반환하는 함수가 0건이라 지금은 안 터지지만, 규칙 자체가 틀렸다.
  (이 소스의 ``void*`` 14건은 전부 **변수 선언**이지 반환 타입이 아니다.)

⚠ 7번째(``suts.py`` RETURN_CHECK)는 더 나빴다 — ``prototype.split("(")[0]`` 은
  **함수 이름까지** 담아서 ``U8 avoid_Overflow(...)`` 같은 이름이면 반환값이 있어도
  void 로 읽힌다. 이 소스엔 그런 이름이 0건이라 **관측된 사례는 없다** — 잠복 위험이다.

## 근본 — 우리 파서가 공백을 잃었다

``report_gen/source_parser._extract_c_prototypes`` 가 ``__interrupt`` 를 반환
타입에 보존하면서(커밋 43a2f99 의 의도) **구분 공백 없이** 이어 붙였다::

    ret_type = f"{interrupt_prefix}{ret_type}"   # "__interrupt" + "void"

그래서 정확일치 사이트는 못 알아보고, 부분문자열 사이트는 **우연히** 맞았다.
근본은 고쳤지만(공백 복원), 이미 나간 산출물·캐시가 붙은 형태를 되돌려 보낸다:
문서 되읽기(``requirements._extract_function_info_from_docx`` 가 ``Prototype``
칸을 그대로 ``info["prototype"]`` 에 넣는다) · ``source_sections`` 프롬프트 캐시
6개. 그래서 아래 ``_RE_GLUED`` 가 붙은 형태도 **되돌린 뒤** 판정한다.

## 규칙

1. 붙어 버린 벤더 한정자를 떼어 놓는다(``__interruptvoid`` → ``__interrupt void``).
2. 한정자를 제거한다 — 저장소가 이미 쓰던 목록(``static|extern|inline|const|
   volatile``)에 **실측으로 확인된** 벤더 한정자 2개를 더한다.
3. 남은 것이 없으면 **반환값 없음**(기존 6곳 전부 ``if ret and …`` 로 같은 답).
4. ``void`` 와의 **정확 일치**로 판정한다 — ``void *`` 는 정규형이 ``void *`` 라
   자동으로 "반환값 있음" 이 된다(부분문자열 규칙이 틀리는 지점).

⚠ 한정자 목록은 **실측 근거가 있는 것만** 담는다. 새 컴파일러 확장을 만나면
   여기에 추가할 것 — 판정을 복제하지 말 것(이 모듈이 생긴 이유다).

⚠ 대소문자: C 는 대소문자를 구분하므로 한정자 제거는 **구분해서** 한다
   (``Static`` 은 키워드가 아니라 타입명일 수 있다 — 기존 7곳 전부 그랬다).
   마지막 ``void`` 비교만 ``lower()`` 로 본다(Win32 ``VOID`` 는 실제로 void 다 —
   기존 7곳 중 3곳이 이미 그렇게 했다).
"""

from __future__ import annotations

import re

# 저장소가 이미 쓰던 표준 한정자(3곳이 같은 목록을 각자 들고 있었다) + 실측 벤더 2개.
_STD_QUALIFIERS = ("static", "extern", "inline", "register", "auto", "const", "volatile")
# 실측 근거: PDS64_RD 헤더의 `__interrupt void Cpu_*(void);` 14건,
#            `Project_Settings/Startup_Code/starts12z.c` 의 `__EXTERN_C void` 1건.
_VENDOR_QUALIFIERS = ("__interrupt", "__EXTERN_C")

_RE_QUALIFIER = re.compile(
    r"\b(?:" + "|".join(re.escape(q) for q in _STD_QUALIFIERS + _VENDOR_QUALIFIERS) + r")\b"
)

# 우리 파서가 공백을 잃어 붙어 버린 형태만 되돌린다.
# ⚠ 뒤가 `void` 인 경우로 **좁힌다** — 넓히면 `__interruptible_t` 같은 진짜 식별자를
#   `ible_t` 로 잘라 먹는다. 실측된 붙음은 `__interrupt`+`void` 하나뿐이다.
_RE_GLUED = re.compile(
    r"(" + "|".join(re.escape(q) for q in _VENDOR_QUALIFIERS) + r")(?=void\b)"
)


def normalize_return_type(raw: object) -> str:
    """반환 타입 문자열에서 한정자를 걷어낸 정규형. 판정용이지 표시용이 아니다."""
    text = " ".join(str(raw or "").split())
    if not text:
        return ""
    text = _RE_GLUED.sub(r"\1 ", text)
    text = _RE_QUALIFIER.sub(" ", text)
    return " ".join(text.split())


def returns_value(raw: object) -> bool:
    """이 반환 타입이 **실제 반환값**을 뜻하는가(= void 가 아닌가)."""
    text = normalize_return_type(raw)
    if not text:
        return False
    # ⚠ `void *` 는 여기서 자동으로 참이 된다 — 정규형이 `"void *"` 라 `"void"` 와 다르다.
    #   전용 분기(`if "*" in text: return True`)를 뒀다가 뮤테이션으로 **등가**임을
    #   확인하고 지웠다(정규형 목록 전수 대조 차이 0). 부분문자열 규칙이 틀리는
    #   지점이므로 계약은 시험으로 고정해 둔다(`test_void_pointer_is_a_real_return_value`).
    return text.lower() != "void"
