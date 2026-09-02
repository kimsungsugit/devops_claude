"""`.validation.md` 줄 라벨의 **단일 출처**.

## 왜 이 모듈이 생겼나

라이터(`report_gen/validation.py::generate_uds_validation_report`)와 리더
(`report_gen/evidence.py::read_docx_validation`)가 라벨 문자열을 각자 들고 있었다.
한쪽만 바뀌어도 예외가 안 나고 **값만 조용히 사라진다** — 실측(2026-09-01):

    리더가 찾던 키   : "Expected functions" / "Matched functions" / "Missing from docx"
    라이터가 쓰던 키 : "Payload 함수 수"    / "문서에 실린 함수(매칭)" / "문서에 없는 소스 함수"

저장소 전체에서 영문 3키를 쓰는 writer 는 **0곳**이었다. 즉 세 필드는 한 번도 채워진
적이 없고, 그 값을 조건으로 그리던 화면(`DocGenStatusBoard.jsx` 의
"문서에 빠진 함수 N개")은 **렌더된 적이 없다**.

`evidence.py` 의 docstring 이 "writer 는 4곳인데 reader 는 0곳이라 화면이 한 번도 본
적이 없다" 라고 자기 존재 이유를 적어 두었는데, 한 층 아래에서 같은 결함이 재발했다.
문자열을 복제하는 한 또 난다 — 그래서 상수를 한 곳에 둔다.

## 계약

- **무의존**(stdlib 조차 안 쓴다). `evidence.py` 는 python-docx 없이 동작해야 하므로
  라벨을 얻자고 `validation.py`(→ `docx_builder` → python-docx)를 import 할 수 없다.
- 값은 backtick **안에 숫자만** 둔다. 단위(`건`)를 안에 넣으면 `int()` 가 실패한다
  (구판 산출물이 그랬다 — 리더는 관용으로 둘 다 읽는다).
- 사람이 읽는 `⚠` 는 라벨 **앞**에 붙되 상수에는 넣지 않는다. 리더가 키에서 선행
  `⚠`/공백을 정규화한다.
"""

# ── 입력 대비 대조 (payload ↔ 문서) ──────────────────────────────────────────
LABEL_EXPECTED_FUNCTIONS = "Payload 함수 수"
LABEL_MATCHED_FUNCTIONS = "문서에 실린 함수(매칭)"
LABEL_MISSING_FROM_DOCX = "문서에 없는 소스 함수"
LABEL_HEADINGS_WITHOUT_PAYLOAD = "데이터 없는 템플릿 heading"

# ── 남의 함수 절 처리 (라운드 12 `unmatched_headings`) ───────────────────────
# `drop` 은 대응 소스가 없는 heading 을 문서에서 **제거**한다. 제거 사실이 없으면
# 리포트는 "빈 heading 이 거의 없다" = 거의 완결된 문서로 보인다.
LABEL_DROPPED_HEADINGS = "문서에서 제거된 heading"
LABEL_UNMATCHED_MODE = "남의 함수 절 처리"

# 값 없이 대조 자체가 불가능했을 때 쓰는 문구 — 0 이나 통과와 구분된다.
VALUE_UNCOMPARABLE = "대조 불가(사이드카 없음/읽기 실패)"

__all__ = [
    "LABEL_EXPECTED_FUNCTIONS",
    "LABEL_MATCHED_FUNCTIONS",
    "LABEL_MISSING_FROM_DOCX",
    "LABEL_HEADINGS_WITHOUT_PAYLOAD",
    "LABEL_DROPPED_HEADINGS",
    "LABEL_UNMATCHED_MODE",
    "VALUE_UNCOMPARABLE",
]
