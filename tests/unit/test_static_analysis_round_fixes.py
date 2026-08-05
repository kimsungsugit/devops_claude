"""정적분석 라운드 — 백엔드 확정 결함 3건의 회귀 가드 (2026-08-05).

## 1. Test Summary TC 통계를 **위치**로 읽었다 (B905)

``_extract_sutr_summary`` 가 6-키 ``zip`` 위치 매핑으로 통계 행을 읽었다. 그런데
이 저장소가 **직접 찍어내는** 회사 v2.02 양식은 'Deviated' 열이 없는 **5열**이다
(``swut_coverage_aggregator`` 가 stamp 하는 라벨 5개). 그러면:

- 미실행 수가 ``deviated`` 자리로 한 칸 밀리고
- ``not_executed`` 는 **대입 자체가 일어나지 않아** 0 으로 남고
- 경고도 없다.

결과: 정합한 산출물 쌍에 "Total TC 불일치" Warning 이 뜨고, 프론트는 미실행 N 건을
Deviation N 건으로 표시했다. 게다가 같은 문서를 ``summarize_test_report`` 로 보면
read-side 보정이 미실행을 채워 넣어서, **같은 문서가 표면마다 다른 값**을 냈다.

## 2. C 파서 소비처의 튜플 폭 불일치

``_extract_c_prototypes``/``_extract_c_definitions`` 가 커밋 43a2f99(2026-04-08)에서
3-tuple → 4-tuple 로 넓어졌는데 ``_scan_source_function_names`` 의 소비처만 3-tuple
로 남아, **C 파일이 하나라도 있으면 100% ValueError** 였다.

기존 테스트가 못 잡은 이유가 중요하다: ``tests/test_coverage_boost.py`` 가
``source_root`` 로 **존재하지 않는 경로**를 넘겨 ``root.exists()`` False 조기 반환에
걸렸다 — 즉 문제의 줄에 **한 번도 도달한 적이 없다**. 그래서 여기서는 실재하는
디렉터리에 실제 ``.c`` 파일을 만든다.

## 3. 그걸 4개월간 감춘 침묵 표면

``jenkins_uds_requirements_preview`` 가 위 예외를 로그 한 줄 없이 삼키고
``function_mapping: null`` + ``ok: True`` 로 응답했다. ①source_root 미지정
②소스에 함수 없음 ③파서 크래시가 전부 같은 ``null`` 이라 구분이 불가능했다.
"""
from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

openpyxl = pytest.importorskip("openpyxl")

from backend.services import swut_consistency_checker as cc  # noqa: E402
from report_gen.source_parser import _scan_source_function_names  # noqa: E402

# 회사 v2.02 양식이 실제로 stamp 하는 5개 라벨 (Deviated 없음).
LABELS_5 = (
    "Total Number of TCs",
    "Number of TCs Tested",
    "Number of TCs Passed",
    "Number of TCs Failed",
    "Number of TCs not executed",
)
# 구 양식 / SITR 6열 (Deviated 포함).
LABELS_6 = (
    "Total Number of TCs",
    "Number of TCs Tested",
    "Number of TCs Passed",
    "Number of TCs Failed",
    "Number of Deviated TCs",
    "Number of TCs not executed",
)


def _summary_wb(labels: tuple[str, ...], values: tuple[int, ...]):
    """Test Summary 시트 하나짜리 워크북 — 라벨 행 + 값 행."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Test Summary")
    for i, lbl in enumerate(labels):
        ws.cell(row=1, column=2 + i, value=lbl)
    for i, val in enumerate(values):
        ws.cell(row=2, column=2 + i, value=val)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return openpyxl.load_workbook(buf, data_only=True)


# ---------------------------------------------------------------------------
# 1. TC 통계 열 매핑
# ---------------------------------------------------------------------------
def test_five_column_form_does_not_shift_not_executed_into_deviated():
    """회사 v2.02(5열)에서 미실행 7건이 Deviation 7건으로 둔갑하면 안 된다."""
    wb = _summary_wb(LABELS_5, (30, 28, 26, 2, 7))
    out = cc._extract_sutr_summary(wb)
    assert out["total_tcs"] == 30
    assert out["tested"] == 28
    assert out["passed"] == 26
    assert out["failed"] == 2
    assert out["not_executed"] == 7, (
        "미실행 값이 not_executed 로 안 들어갔다 — 위치 매핑이면 deviated 로 밀린다"
    )
    assert out["deviated"] == 0, (
        f"Deviated 열이 없는 양식인데 deviated={out['deviated']} — 미실행이 밀려 들어왔다"
    )


def test_six_column_form_still_reads_both():
    """구 양식(6열)은 그대로 동작해야 한다 — 새 매핑이 회귀를 만들지 않는지."""
    wb = _summary_wb(LABELS_6, (420, 419, 415, 4, 4, 1))
    out = cc._extract_sutr_summary(wb)
    assert (out["total_tcs"], out["tested"], out["passed"], out["failed"]) == (420, 419, 415, 4)
    assert out["deviated"] == 4
    assert out["not_executed"] == 1


def test_column_order_change_is_followed_by_label_not_position():
    """열 순서가 바뀌어도 라벨을 따라간다 — 위치 매핑이면 전부 어긋난다."""
    shuffled = (
        "Total Number of TCs",
        "Number of TCs not executed",
        "Number of TCs Tested",
        "Number of TCs Passed",
        "Number of TCs Failed",
    )
    wb = _summary_wb(shuffled, (30, 7, 28, 26, 2))
    out = cc._extract_sutr_summary(wb)
    assert out["not_executed"] == 7
    assert out["tested"] == 28
    assert out["passed"] == 26


def test_unmappable_form_warns_instead_of_fabricating_zeros():
    """라벨도 못 읽고 열 수도 안 맞으면 **채우지 않고 경고**한다.

    0 으로 채우면 '미실행 0건' 이라는 확정적 부정 답변이 되어, 파싱 실패와
    진짜 0 이 구분되지 않는다 — 이 저장소의 '미계산은 0 이 아니라 —' 규약.
    """
    summary: dict = {"deviated": 0, "not_executed": 0}
    warnings: list[str] = []
    cc._fill_tc_stats(
        summary,
        header_pairs=[(2, "알 수 없는 라벨"), (3, "또 다른 라벨")],
        value_pairs=[(2, "30"), (3, "7")],
        out_warnings=warnings,
    )
    assert warnings, "매핑 불가인데 경고가 없다 — 조용히 틀린 값을 낸다"
    assert "not_executed" in warnings[0] or "매핑 불가" in warnings[0]
    assert summary["deviated"] == 0 and summary["not_executed"] == 0


def test_legacy_positional_fallback_still_works_when_counts_match():
    """라벨이 전혀 없어도 열 수가 정확히 6이면 구 동작(위치)을 유지한다."""
    summary: dict = {}
    cc._fill_tc_stats(
        summary,
        header_pairs=[],
        value_pairs=[(2, "30"), (3, "28"), (4, "26"), (5, "2"), (6, "1"), (7, "7")],
        out_warnings=None,
    )
    assert summary["total_tcs"] == 30 and summary["not_executed"] == 7


# ---------------------------------------------------------------------------
# 2. C 파서 소비처
# ---------------------------------------------------------------------------
def test_scan_source_function_names_reaches_the_parser(tmp_path):
    """**실재하는** .c 파일로 호출한다.

    ⚠ 기존 유일한 테스트(tests/test_coverage_boost.py)는 존재하지 않는 경로를
      넘겨 `root.exists()` False 로 조기 반환했다. 그래서 4개월간 100% 크래시하는
      코드가 초록이었다. 이 테스트의 존재 이유가 그것이다.
    """
    (tmp_path / "a.c").write_text(
        "void Foo(void);\nint Bar(int x) { return x; }\n", encoding="utf-8"
    )
    out = _scan_source_function_names(str(tmp_path))
    assert out["scanned"] == 1
    assert "Foo" in out["names"], f"프로토타입을 못 읽었다: {out}"
    assert "Bar" in out["names"], f"정의를 못 읽었다: {out}"


def test_scan_source_survives_future_tuple_width_changes(tmp_path):
    """추출기 튜플 폭이 또 바뀌어도 이 소비처는 안 깨진다(`fn, *_rest`)."""
    src = (REPO / "report_gen/source_parser.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_scan_source_function_names")
    starred = 0
    for node in ast.walk(fn):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
            if any(isinstance(el, ast.Starred) for el in node.target.elts):
                starred += 1
    assert starred >= 2, (
        "고정 폭 언패킹으로 되돌아갔다 — 추출기 폭이 바뀌면 다시 ValueError 가 된다"
    )


# ---------------------------------------------------------------------------
# 3. 침묵 표면
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 4. 이번 라운드 룰 승격이 실제로 켜져 있는가
# ---------------------------------------------------------------------------
def test_ratchet_actually_detects_promoted_rules(tmp_path):
    """승격한 룰이 **진짜로** ruff 호출에 반영되는지 — 상수만 보지 말고 돌려본다.

    (pytest tmp_path 는 이 저장소에선 `<repo>/.codex_tmp/...` 라 repo 하위이고,
     ratchet 의 경로 정규화가 성립한다.)
    """
    import sys as _sys

    _sys.path.insert(0, str(REPO / "scripts"))
    import ruff_ratchet  # noqa: PLC0415

    probe = tmp_path / "_promoted_probe.py"
    probe.write_text(
        "def f(a, b):\n"
        "    return list(zip(a, b))\n",          # B905
        encoding="utf-8",
    )
    codes = {code for _f, _line, code, _msg in ruff_ratchet._collect([str(probe)])}
    assert "B905" in codes, (
        f"승격한 B905 가 검출되지 않는다 — --extend-select 가 빠졌다. 검출: {sorted(codes)}"
    )


def test_promoted_rule_set_covers_this_rounds_real_defects():
    """이번 라운드에 **실제 결함을 낸** 룰군이 승격 목록에 남아 있는지."""
    import sys as _sys

    _sys.path.insert(0, str(REPO / "scripts"))
    import ruff_ratchet  # noqa: PLC0415

    selected = set(ruff_ratchet._EXTRA_SELECT.split(","))
    # ASYNC: 이벤트 루프 점유(browse_file 최대 600초) / B905: 미실행 TC → Deviation 둔갑
    for must in ("ASYNC", "B905", "B017", "S608", "S307"):
        assert must in selected, f"{must} 가 승격 목록에서 빠졌다"
    # ⚠ S603/S607 은 **의도적 제외**다(153건 중 실제 결함 2건 = 98.7% 거짓양성).
    #   되살리면 곧 무시되는 게이트가 된다 — 그 결정을 여기서 못 박는다.
    assert "S603" not in selected and "S607" not in selected, (
        "S603/S607 을 켰다 — 거짓양성 98.7% 라 게이트가 무력해진다. 의도한 변경이면 "
        "ruff_ratchet._EXTRA_SELECT 주석의 근거부터 갱신할 것"
    )


def test_requirements_preview_reports_failures_instead_of_null():
    """실패를 ``null`` 로 접지 않고 사유를 응답에 싣는지 — 소스 수준 가드.

    엔드포인트 전체를 띄우려면 Jenkins 산출물 픽스처가 필요해서, 여기서는
    ``except`` 블록이 사유를 버리지 않는다는 **구조**를 본다.
    """
    src = (REPO / "backend/routers/jenkins.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "jenkins_uds_requirements_preview")
    # ⚠ 이 핸들러에는 문서 **한 건씩** 읽다 실패하면 `text = ""` 로 넘어가는
    #   레거시 except 가 5곳 더 있다. 그건 이 저장소가 ratchet 로 관리하는 침묵
    #   backlog 라 여기서 일괄 차단하지 않는다(그러면 무관한 변경까지 막힌다).
    #   여기서 보는 것은 **추적성 대조 두 건**을 감싼 try 뿐이다.
    guarded = {"generate_uds_requirements_compare", "generate_uds_function_mapping"}
    silent: list[str] = []
    checked = 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        called = {
            (c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", ""))
            for c in ast.walk(node) if isinstance(c, ast.Call)
        }
        if not (called & guarded):
            continue
        checked += 1
        for h in node.handlers:
            # 사유를 이름으로 붙잡지 않으면 그 자리에서 원인이 소실된다.
            if h.name is None:
                silent.append(f"line {h.lineno}: {sorted(called & guarded)} 의 예외를 버린다")
    assert checked == 2, f"대상 try 블록을 {checked}개 찾았다 — 2개여야 한다(구조 변경?)"
    assert not silent, (
        "추적성 대조 실패 사유를 버리는 except 가 남아 있다:\n  " + "\n  ".join(silent)
    )
    assert '"errors": errors' in src or "errors\"" in src, (
        "실패 사유를 응답에 싣지 않는다 — null 과 '계산 실패' 가 구분되지 않는다"
    )
