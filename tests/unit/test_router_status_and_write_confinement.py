# -*- coding: utf-8 -*-
"""라우터 두 축 — ①의도한 4xx 가 살아남는가 ②클라이언트가 준 **쓰기 경로**가 봉인되는가.

## 축 B — `except Exception` 이 4xx 를 500 으로 바꾸고 있었다 (실측 2026-08-19)

    V.vcast_download_report("no_such.xlsx")
      → 500  "Download error: 404: Report file not found"      ← 404 가 사라졌다
    V.vcast_download_report("../../../x.xlsx")
      → 500  "Download error: path traversal not allowed"      ← 이탈 시도가 서버 장애로

결과가 셋이다: ①클라이언트가 자기 입력 문제를 서버 장애로 읽는다 ②모니터링에 없는 장애가
쌓이고 진짜 장애가 묻힌다 ③`str(e)` 가 응답에 실려 **내부 경로가 새어 나간다**.

AST 로 전수 조사한 결과 `except Exception` 이 4xx 를 먹는 자리는 **4곳**이었다
(`excel.py` ×2 · `vcast.py` ×2). `safe_resolve_under` 의 ValueError 를 **400 으로** 바꾸는
14곳은 결함이 아니다 — 이탈은 실제로 클라이언트 오류다.

## 축 A — 쓰기 경로만 봉인한다 (읽기는 설계상 열려 있다)

⚠ **읽기를 같이 잠그면 안 된다.** 이 앱은 요구문서·소스가 저장소 밖에 사는 것을 전제한다
  (`_is_allowed_req_doc` 이 위치가 아니라 **확장자만** 본다. CLAUDE.md 의 요구문서 경로도
  `D:/Project/devops/260105/docs/` 로 저장소 밖이다). `sds_path`/`source_path` 를 봉인하면
  정상 사용이 깨지고, 다른 읽기 경로와도 어긋난다.

  **쓰기는 근거가 없다.** 산출물을 임의 위치에 떨궈야 할 이유가 이 저장소엔 없고,
  `local_editor_write` 는 이미 같은 루트로 잠겨 있다. 봉인 없이 남아 있던 쓰기 4곳:

      /api/exports/pdf/report                        output_path  ← 경로도 **내용도** 클라이언트
      /api/exports/pdf/convert                       output_path
      /api/local/project-setup/generate-component-map  output_dir
      /api/local/project-setup/generate-override       output_dir

  프론트는 넷 중 어디에도 경로를 보내지 않는다(`output_dir` 은 아예 미전송) — 봉인해도
  UI 파손이 없음을 확인하고 넣었다.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.routers import exports as X
from backend.routers import local as L
from backend.routers import vcast as V
from backend.services.paths import is_under_any, trusted_roots

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def outside_dir():
    """신뢰 루트 **밖**이면서 테스트가 **자기 손으로 지우는** 디렉터리.

    ⚠ 둘 다 만족해야 한다. 봉인이 없는 상태(뮤턴트·미래 회귀)에서 이 테스트는 **실제로
      쓴다** — 그게 검사의 본질이다. 두 번 틀렸다:

      ① `C:/Windows/Temp/...` 를 썼더니 뮤턴트가 거기에 18KB PDF 를 만들었고, 그 잔재가
         다음 실행의 `not exists()` 단언을 깨뜨렸다(같은 세션에서 `D:\\etc\\passwd.xlsx`
         로 이미 겪고도 되풀이했다).
      ② 그래서 `tmp_path` 로 바꿨더니 **이 저장소의 conftest 가 `tmp_path` 를 저장소 안
         (`.codex_tmp/`)으로 돌려놔** 신뢰 루트 **안**이 됐고, 403 이 안 나 4건이 깨졌다.
         "pytest 기본 동작"을 가정하면 안 된다 — 이 저장소는 그걸 바꿔 뒀다.

      그래서 시스템 temp 에 직접 만들고 직접 지운다.
    """
    import shutil
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="confine_probe_"))
    assert not is_under_any(d, trusted_roots()), f"탐침이 신뢰 루트 안이다: {d}"
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def outside(outside_dir):
    return outside_dir / "pwned_by_test.pdf"


# --------------------------------------------------------------------------- #
# 축 B — 의도한 상태코드가 살아남는다
# --------------------------------------------------------------------------- #


class TestIntendedStatusSurvives:
    def test_missing_report_is_404_not_500(self):
        with pytest.raises(HTTPException) as ei:
            V.vcast_download_report("no_such_report_file.xlsx")
        assert ei.value.status_code == 404, (
            f"404 가 {ei.value.status_code} 로 바뀌었다 — `except HTTPException: raise` 가 사라졌는가")

    def test_traversal_is_400_not_500(self):
        with pytest.raises(HTTPException) as ei:
            V.vcast_download_report("../../../etc/x.xlsx")
        assert ei.value.status_code == 400, ei.value.status_code

    def test_invalid_excel_params_is_400_not_500(self):
        from backend.routers import excel as E
        from backend.schemas import ExcelCompareRequest

        with pytest.raises(HTTPException) as ei:
            E.excel_compare(ExcelCompareRequest(
                path_source="C:/definitely_missing_1.xlsx",
                path_target="C:/definitely_missing_2.xlsx"))
        assert ei.value.status_code == 400, ei.value.status_code

    @pytest.mark.parametrize("call", [
        lambda: V.vcast_download_report("no_such_report_file.xlsx"),
        lambda: V.vcast_download_report("../../../etc/x.xlsx"),
    ])
    def test_detail_does_not_leak_absolute_paths(self, call):
        """⚠ `detail=f"…{str(e)}"` 는 절대경로를 그대로 응답에 싣는다."""
        with pytest.raises(HTTPException) as ei:
            call()
        detail = str(ei.value.detail)
        assert str(REPO) not in detail, detail
        assert "C:\\" not in detail and "D:\\" not in detail, detail


class TestNoHandlerRebuildsTheDefect:
    """구조 가드 — 고친 4곳에서 `except HTTPException: raise` 가 사라지면 잡는다.

    ⚠ 주석은 걷어내고 본다. 결함을 설명한 주석이 바로 그 문자열을 담고 있어, 원문 전체
      검색은 자기 설명에 걸린다(이 저장소에서 이미 한 번 겪었다).

    ⚠ 함수 경계는 **문자열 마커가 아니라 `inspect.getsource`** 로 잡는다. 처음엔 "다음
      함수 이름"을 끝 마커로 썼는데, 마지막 함수는 그 마커가 아예 없어 슬라이스가 파일
      끝까지 갔다 — 뒤에 다른 함수가 붙으면 **남의 핸들러를 보고 통과**한다.
    """

    @pytest.fixture(scope="class")
    def sites(self):
        from backend.routers import excel as E

        return [
            ("vcast_download_report", V.vcast_download_report),
            ("vcast_process_jenkins", V.vcast_process_jenkins),
            ("excel_compare", E.excel_compare),
            ("excel_compare_upload", E.excel_compare_upload),
        ]

    def test_http_exception_is_reraised_first(self, sites):
        for name, fn in sites:
            code = [ln for ln in inspect.getsource(fn).splitlines()
                    if not ln.lstrip().startswith("#")]
            assert any("except HTTPException" in ln for ln in code), (
                f"{name}: HTTPException 재-raise 가 사라졌다 — 4xx 가 500 이 된다")
            assert not any('detail=f"' in ln and "{str(e)}" in ln for ln in code), (
                f"{name}: 내부 예외 문자열을 응답에 다시 싣는다")

    def test_the_site_list_is_not_empty(self, sites):
        """⚠ 픽스처가 비면 위 루프가 아무것도 안 보고 통과한다."""
        assert len(sites) == 4, sites


# --------------------------------------------------------------------------- #
# 축 A — 쓰기 경로 봉인
# --------------------------------------------------------------------------- #


class TestClientWritePathsAreConfined:
    def test_pdf_report_outside_is_403(self, outside):
        with pytest.raises(HTTPException) as ei:
            X.generate_pdf_report(X.PdfReportRequest(
                title="t", sections=[], output_path=str(outside)))
        assert ei.value.status_code == 403, ei.value.status_code
        assert not outside.exists(), "봉인 밖에 파일이 생겼다"

    def test_pdf_convert_outside_is_403(self, outside):
        with pytest.raises(HTTPException) as ei:
            X.convert_to_pdf(X.PdfConvertRequest(
                source_path=str(REPO / "README.md"), output_path=str(outside)))
        assert ei.value.status_code == 403, ei.value.status_code
        assert not outside.exists(), "봉인 밖에 파일이 생겼다"

    @pytest.mark.parametrize("fn,kwargs", [
        ("local_generate_component_map", {"sds_path": "x.docx", "source_root": "y"}),
        ("local_generate_override", {"uds_path": "x.docx"}),
    ])
    def test_project_setup_output_dir_outside_is_403(self, fn, kwargs, outside_dir):
        with pytest.raises(HTTPException) as ei:
            getattr(L, fn)(output_dir=str(outside_dir), **kwargs)
        assert ei.value.status_code == 403, ei.value.status_code
        assert list(outside_dir.iterdir()) == [], "봉인 밖에 파일이 생겼다"

    def test_inside_repo_is_accepted(self):
        """⚠ 봉인이 정상 경로까지 막으면 그건 고친 게 아니라 부순 것이다."""
        from backend.services.paths import confine

        got = confine(str(REPO / "reports" / "x.pdf"), what="output_path")
        assert got.is_relative_to(REPO.resolve())

    def test_error_does_not_disclose_allowed_roots(self):
        """실패 응답이 허용 루트를 알려 주면 그 자체가 정찰 정보다."""
        from backend.services.paths import confine

        with pytest.raises(HTTPException) as ei:
            confine("C:/Windows", what="output_dir")
        detail = str(ei.value.detail)
        assert "devops_pro_cache" not in detail
        assert str(REPO) not in detail


class TestReadPathsStayOpenOnPurpose:
    """⚠ **결정 트립와이어** — 읽기까지 봉인하면 정상 사용이 깨진다.

    요구문서·소스는 저장소 밖에 산다(CLAUDE.md 의 `D:/Project/devops/260105/docs/`).
    누군가 "일관성"을 이유로 여기에 봉인을 붙이면 이 테스트가 깨지고, 그때 위 판단을
    다시 읽게 된다. 값이 없다고 지우지 말 것.
    """

    def test_source_path_is_not_confined(self):
        src = inspect.getsource(X.convert_to_pdf)
        code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
        joined = "\n".join(code)
        assert "confine(req.output_path" in joined, "쓰기 봉인이 사라졌다"
        assert "confine(req.source_path" not in joined, (
            "읽기까지 봉인됐다 — 저장소 밖 요구문서/산출물을 못 읽게 된다")

    def test_sds_and_uds_reads_are_not_confined(self):
        for fn in (L.local_generate_component_map, L.local_generate_override):
            src = inspect.getsource(fn)
            code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
            assert "confine(output_dir" in code, f"{fn.__name__}: 쓰기 봉인이 사라졌다"
            for read_arg in ("sds_path", "source_root", "uds_path"):
                assert f"confine({read_arg}" not in code, (
                    f"{fn.__name__}: 읽기 인자 {read_arg} 까지 봉인됐다")


class TestTrustedRootsHaveASingleSource:
    """같은 판정이 세 벌로 흩어져 있던 게 봉인 공백의 원인이었다."""

    def test_local_delegates_to_paths(self):
        a = sorted(str(p) for p in L._allowed_request_roots())
        b = sorted(str(p) for p in trusted_roots())
        assert a == b, f"허용 루트가 다시 갈라졌다\n  local={a}\n  paths={b}"

    def test_roots_do_not_widen_with_config(self, monkeypatch):
        """⚠ 설정값으로 넓히면 `/api/local/*` 20곳이 조용히 함께 넓어진다."""
        import config

        monkeypatch.setattr(config, "DEFAULT_PROJECT_ROOT", "C:/Windows", raising=False)
        monkeypatch.setattr(config, "JENKINS_SERVER_ROOTS", ["C:/Windows"], raising=False)
        roots = [str(p) for p in trusted_roots()]
        assert not any("Windows" in r for r in roots), roots
