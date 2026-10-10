"""요청서 부록 산출물의 **생산자 단일성** 가드.

`docs/plans/UDS_RelatedID_SwFn_부록/` 의 TSV 는 각각 스크립트 하나만 써야 한다.
생산자가 둘이면 나중에 도는 쪽이 조용히 덮는다 — 경고도 없고 diff 를 봐야만 안다.

실사고(라운드119): 대상이 900행 → 앱 계층 390행으로 재산정되며 부록 A 의 소유권이
`uds_appendix.py` → `swfn_assign_appendix.py` 로 넘어갔는데, 구 스크립트가 A 를 계속
쓰고 있었다. 그런데 요청서 §6 의 실행 순서가 하필

    swfn_assign_appendix.py   → 390행 / 8열
    uds_appendix.py           → 900행 / 5열   ← 되돌아감

라, **문서에 적힌 절차대로 재생성하면 제외했던 인프라 256행이 되살아났다.** 그 256행은
부트로더 flash 루틴·SPI 드라이버라 앱 설계ID를 붙이면 거짓 추적이 되는 것들이다.
"""
from __future__ import annotations

import collections
import re
from pathlib import Path

import pytest

APPENDIX_DIR = Path(__file__).resolve().parents[2] / "docs" / "plans" / "UDS_RelatedID_SwFn_부록"
# `OUT / "appendix_X.tsv"` 형태의 쓰기 대상만 뽑는다(읽기는 baseline.json 이라 안 걸린다).
_WRITE_RE = re.compile(r"""OUT\s*/\s*["'](appendix_[^"']+\.tsv)["']""")


def _producers() -> dict:
    """{산출물 파일명: [그걸 쓰는 스크립트, ...]}"""
    out = collections.defaultdict(list)
    for py in sorted(APPENDIX_DIR.glob("*.py")):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for name in set(_WRITE_RE.findall(text)):
            out[name].append(py.name)
    return out


@pytest.mark.skipif(not APPENDIX_DIR.is_dir(), reason="부록 디렉터리 없음")
def test_each_appendix_has_exactly_one_producer():
    dupes = {k: v for k, v in _producers().items() if len(v) > 1}
    assert not dupes, (
        "부록 산출물에 생산자가 둘 이상이다 — 나중에 도는 쪽이 조용히 덮는다: "
        + "; ".join(f"{k} ← {sorted(v)}" for k, v in sorted(dupes.items()))
    )


@pytest.mark.skipif(not APPENDIX_DIR.is_dir(), reason="부록 디렉터리 없음")
def test_appendix_a_is_owned_by_the_assignment_script():
    """부록 A(요청 대상)는 계층 필터·후보 산출을 하는 스크립트만 써야 한다.

    구 스크립트가 다시 A 를 쓰기 시작하면 대상이 900행으로 되돌아간다.
    """
    owners = _producers().get("appendix_A_swcom_only.tsv", [])
    assert owners == ["swfn_assign_appendix.py"], f"부록 A 생산자: {owners}"


@pytest.mark.skipif(not APPENDIX_DIR.is_dir(), reason="부록 디렉터리 없음")
def test_shipped_appendix_a_is_the_scoped_one():
    """저장소에 실린 부록 A 가 앱 계층 스키마인지 — 구 5열 판이 커밋되면 잡는다."""
    tsv = APPENDIX_DIR / "appendix_A_swcom_only.tsv"
    if not tsv.exists():
        pytest.skip("부록 A 미생성")
    lines = tsv.read_text(encoding="utf-8-sig").splitlines()
    header = lines[0].split("\t")
    assert "계층" in header and "팀 확정" in header, f"구 스키마로 보인다: {header}"
    # 계층 열은 전부 APP — 인프라가 섞이면 거짓 추적을 요청하게 된다.
    li = header.index("계층")
    layers = {ln.split("\t")[li] for ln in lines[1:] if ln.strip()}
    assert layers == {"APP"}, f"계층 열에 인프라가 섞였다: {sorted(layers)}"


@pytest.mark.skipif(not APPENDIX_DIR.is_dir(), reason="부록 디렉터리 없음")
@pytest.mark.parametrize("name", [
    "appendix_A_swcom_only.tsv",
    "appendix_B_swfn_catalog.tsv",
    "appendix_C_doc_code_drift.tsv",
    "appendix_D_scope_boundary.tsv",
])
def test_tsv_column_contract(name):
    """헤더와 전 행의 열 수가 같아야 한다 — 과거 CSV 열 밀림 전례."""
    tsv = APPENDIX_DIR / name
    if not tsv.exists():
        pytest.skip(f"{name} 미생성")
    lines = [ln for ln in tsv.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    ncol = len(lines[0].split("\t"))
    bad = [i for i, ln in enumerate(lines[1:], 2) if len(ln.split("\t")) != ncol]
    assert not bad, f"{name}: 헤더 {ncol}열, 어긋난 행 {bad[:5]}"
