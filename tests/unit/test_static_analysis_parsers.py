"""정적분석 보조 파서(CPD/QAC HIS/CodeEye) 단위 테스트.

실데이터(PDS64_RD) 레이아웃 기반 합성 픽스처. PDF 비의존(텍스트/XML 직접).
"""
from backend.services.static_analysis_parsers import (
    parse_codeeye_text,
    parse_cpd_xml,
    parse_qac_his_text,
)

# ── CPD (PMD CPD XML) ──────────────────────────────────────────────────
_CPD_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<pmd-cpd>
  <duplication lines="31" tokens="105">
    <file path="C:\\x\\Ap_DoorCtrl_PDS.c" line="10"/>
    <file path="C:\\x\\Ap_DoorCtrl_PDS.c" line="50"/>
  </duplication>
  <duplication lines="28" tokens="188">
    <file path="C:\\x\\Vectors.c" line="73"/>
    <file path="C:\\x\\Vectors.c" line="100"/>
  </duplication>
</pmd-cpd>
"""


def test_cpd_summary():
    d = parse_cpd_xml(_CPD_XML)
    assert d["ok"] is True
    assert d["duplication_blocks"] == 2
    assert d["total_dup_lines"] == 59
    assert d["total_tokens"] == 293
    assert d["files_involved"] == 2  # distinct full paths


def test_cpd_top_blocks_sorted_and_dedup_files():
    d = parse_cpd_xml(_CPD_XML)
    # 라인 큰 순 정렬
    assert d["top_blocks"][0]["lines"] == 31
    # 같은 파일 2 fragment → 파일명 dedup
    assert d["top_blocks"][0]["files"] == ["Ap_DoorCtrl_PDS.c"]
    assert d["top_blocks"][0]["fragments"] == 2


def test_cpd_malformed_graceful():
    d = parse_cpd_xml(b"<not-xml")
    assert d["ok"] is False


# ── QAC HIS Metrics ────────────────────────────────────────────────────
_QAC_TXT = """Project : C:/workspace/QAC/PRQA_PDSM
Status at: 15 Jan, 2024 at 16:43:58
Function: g_foo
CALLS RETURN v(G) PATH LEVEL STMT PARAM GOTO CALLING
Metric
(STCAL) (STM19) (STCYC) (STPTH) (STMIF) (STST3) (STPAR) (STGTO) (STM29)
Values 0 1 12 2 1 4 3 0 3
Function: g_bar
CALLS RETURN v(G) PATH LEVEL STMT PARAM GOTO CALLING
Metric
(STCAL) (STM19) (STCYC) (STPTH) (STMIF) (STST3) (STPAR) (STGTO) (STM29)
Values 0 1 3 2 1 4 3 0 3
"""


def test_qac_his_vg_extraction():
    d = parse_qac_his_text(_QAC_TXT)
    assert d["ok"] is True
    assert d["summary"]["function_count"] == 2
    # STCYC(3번째 Values)이 v(G)
    assert d["summary"]["vg_max"] == 12
    assert d["summary"]["vg_over_10"] == 1
    assert d["summary"]["vg_mean"] == 7.5
    assert d["summary"]["project"] == "C:/workspace/QAC/PRQA_PDSM"
    # 복잡도 상위 함수 정렬
    assert d["top_functions"][0] == {"function": "g_foo", "vg": 12}


def test_qac_his_empty():
    d = parse_qac_his_text("no functions here")
    assert d["ok"] is False
    assert d["summary"]["function_count"] == 0


def test_qac_his_wide_gap_not_dropped():
    # F6: Function↔Values 간격이 200자를 크게 넘어도 블록 분할로 함수를 놓치지 않는다
    # (구 고정 폭 윈도우 [\\s\\S]{0,200}?는 이 간격에서 함수를 침묵 누락).
    filler = "\n".join("noise " * 8 for _ in range(12))  # 200자 이상
    txt = f"Function: g_wide\n{filler}\nValues 0 1 9 2 1 4 3 0 3\n"
    d = parse_qac_his_text(txt)
    assert d["summary"]["function_count"] == 1
    assert d["top_functions"][0] == {"function": "g_wide", "vg": 9}


def test_qac_his_no_cross_attribution():
    # F6: Values 없는 함수 뒤 다른 함수가 와도 다음 함수의 Values를 훔치지 않는다(블록 경계).
    # 구 정규식은 g_novalue에 g_has의 Values(5)를 잘못 귀속했다.
    txt = "Function: g_novalue\n(no metrics here)\nFunction: g_has\nValues 0 1 5 2 1 4 3 0 3\n"
    d = parse_qac_his_text(txt)
    fns = {f["function"]: f["vg"] for f in d["top_functions"]}
    assert fns == {"g_has": 5}
    assert d["summary"]["function_count"] == 1


# ── CodeEye (OSS 라이선스) ─────────────────────────────────────────────
_CE_TXT = """검사명칭 : PDS 검사언어 : C
검사목적 : 라이선스 확인 사용자지정 유사율 범위 : 0 ~ 100%
검사파일개수 : 110건 (1.89 MB)
검사파일개수 : 110건 검사 성공 파일 : 110건
검사시작시간 : 2022-05-23 09:12 검사 실패 파일 : 0건
"""


def test_codeeye_summary():
    d = parse_codeeye_text(_CE_TXT)
    assert d["ok"] is True
    assert d["summary"]["files_checked"] == 110
    assert d["summary"]["files_success"] == 110
    assert d["summary"]["files_fail"] == 0
    assert d["summary"]["inspection_name"] == "PDS"


def test_codeeye_empty():
    d = parse_codeeye_text("관련 없는 텍스트")
    assert d["ok"] is False
