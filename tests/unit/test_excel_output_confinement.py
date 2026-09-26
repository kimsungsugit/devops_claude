# -*- coding: utf-8 -*-
"""VectorCAST Excel 생성 산출물 경로 — **봉인**과 **선점**.

## 무엇이 틀렸었나 (실측 2026-08-19)

`/api/vcast/generate-excel` 은 클라이언트가 준 `output_filename` 을 그대로 붙였다::

    output_path = output_dir / filename          # 봉인 아님

`..` 는 물론이고 **절대경로는 기준 디렉터리를 통째로 대체한다**::

    Path("D:/…/reports/vcast_excel") / "C:/Windows/Temp/x.xlsx"  ==  C:/Windows/Temp/x.xlsx
    Path("D:/…/reports/vcast_excel") / "../../../evil.xlsx"      ==  D:/Project/devops/evil.xlsx

제약은 확장자 강제(`.xlsx`) 하나뿐이었으므로 **백엔드가 쓸 수 있는 곳의 임의 .xlsx 를
덮어쓸 수 있었다** — 입력 요구문서(`260105/docs/*.xlsx`)를 포함해서.

⚠ 같은 파일의 **다운로드** 엔드포인트(`vcast_download_report`)는 이미 `safe_resolve_under`
를 쓰고 있었다. 읽기만 봉인하고 **쓰기를 열어 둔 비대칭**이라, 파일 하나만 봐서는
"봉인돼 있다"로 읽힌다. 그래서 구조 가드를 함께 둔다.

## 충돌 축은 '같은 초'가 아니라 '같은 날'이다

프론트가 보내는 이름은 **날짜 단위**다 —
`ReportGenSection.jsx:421` `vcast_${type}_${YYYYMMDD}.xlsx`. 사용자·프로젝트 키가 없으므로
같은 날 같은 종류를 만든 두 사용자는 **확정적으로** 같은 경로를 쓴다(경합이 아니다).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi import HTTPException

from backend.routers import vcast as V
from backend.schemas import VCastGenerateExcelRequest


@pytest.fixture()
def out_root(tmp_path, monkeypatch):
    """`repo_root` 를 tmp 로 돌려 산출물이 저장소에 안 남게 한다."""
    monkeypatch.setattr(V, "repo_root", tmp_path)
    return tmp_path / "reports" / "vcast_excel"


@pytest.fixture()
def gen_ok(monkeypatch):
    """generate_testcase_excel 대역 — 실제로 내용을 써서 '성공'을 흉내낸다."""
    calls: list[Path] = []

    def _fake(_tcbank, out_path, _mode) -> bool:
        calls.append(Path(out_path))
        Path(out_path).write_bytes(b"XLSX-PAYLOAD")
        return True

    monkeypatch.setattr(V, "generate_testcase_excel", _fake)
    return calls


def _req(**kw: Any) -> VCastGenerateExcelRequest:
    payload: Dict[str, Any] = {"parsed_data": {}, "mode": "TestCase"}
    payload.update(kw)
    return VCastGenerateExcelRequest(**payload)


class TestOutputFilenameIsConfined:
    """클라이언트 문자열이 출력 디렉터리 밖을 못 가리킨다.

    ⚠ **이탈 대상은 반드시 `tmp_path` 안에 떨어지게 고른다.** 봉인이 없는 상태(뮤테이션,
      혹은 미래의 회귀)에서 이 테스트는 **실제로 쓴다** — 그게 검사의 본질이다. 처음엔
      `/etc/passwd.xlsx` 를 썼다가 뮤테이션 실행이 머신에 `D:\\etc\\passwd.xlsx` 를 만들었고,
      그 디렉터리가 생긴 탓에 **무관한 테스트**(`test_swut_asil_resolver`, `/etc` 가 실재
      디렉터리로 해석됨)가 깨졌다. 이탈은 증명하되 샌드박스는 넘지 않는다.
    """

    @staticmethod
    def _inside_tmp(tmp_path: Path, out_root: Path, rel: str) -> Path:
        """이탈이 성공했을 때 **어디에 떨어지는지**를 미리 계산하고, tmp 안임을 강제한다."""
        target = (out_root / rel).resolve()
        assert not target.is_relative_to(out_root.resolve()), f"이탈이 아니다: {rel}"
        assert target.is_relative_to(tmp_path.resolve()), (
            f"이탈 대상이 샌드박스 밖이다: {target} — 테스트가 머신을 오염시킨다")
        return target

    @pytest.mark.parametrize("rel", [
        "../../evil.xlsx",
        "..\\..\\evil.xlsx",
        "sub/../../../escape.xlsx",
    ])
    def test_relative_escape_is_rejected_and_writes_nothing(self, out_root, gen_ok, tmp_path, rel):
        target = self._inside_tmp(tmp_path, out_root, rel)
        with pytest.raises(HTTPException) as ei:
            V.vcast_generate_excel(_req(output_filename=rel))
        assert ei.value.status_code == 400, f"{rel!r} 가 400 이 아니다: {ei.value.status_code}"
        assert "output_filename" in str(ei.value.detail)
        assert not target.exists(), f"봉인 밖에 파일이 생겼다: {target}"
        assert not gen_ok, "생성기가 호출됐다 — 봉인이 생성 뒤에 걸려 있다"

    def test_absolute_path_replaces_the_base_and_is_rejected(self, out_root, gen_ok, tmp_path):
        """⚠ `..` 만 막으면 부족하다 — **절대경로는 기준 디렉터리를 통째로 대체한다**."""
        target = tmp_path / "abs_escape.xlsx"
        assert (out_root / str(target)) == target, "이 플랫폼에선 절대경로가 base 를 안 덮는다"
        with pytest.raises(HTTPException) as ei:
            V.vcast_generate_excel(_req(output_filename=str(target)))
        assert ei.value.status_code == 400
        assert not target.exists(), f"절대경로로 밖에 썼다: {target}"
        assert not gen_ok

    def test_normal_name_still_works(self, out_root, gen_ok):
        resp = V.vcast_generate_excel(_req(output_filename="report.xlsx"))
        assert Path(resp.path).parent == out_root.resolve()
        assert Path(resp.path).read_bytes() == b"XLSX-PAYLOAD"

    def test_extension_is_still_appended(self, out_root, gen_ok):
        V.vcast_generate_excel(_req(output_filename="noext"))
        assert gen_ok[0].name == "noext.xlsx", gen_ok[0]


class TestSameNameDoesNotOverwrite:
    """같은 날 두 사용자가 같은 이름을 보내도 앞 산출물이 살아 있다."""

    def test_second_request_gets_a_new_path(self, out_root, gen_ok):
        first = V.vcast_generate_excel(_req(output_filename="vcast_testcase_20260819.xlsx"))
        Path(first.path).write_bytes(b"USER-A")

        second = V.vcast_generate_excel(_req(output_filename="vcast_testcase_20260819.xlsx"))
        assert Path(second.path) != Path(first.path), "두 요청이 같은 경로를 받았다"
        assert Path(first.path).read_bytes() == b"USER-A", "앞 사용자의 산출물이 덮였다"

    def test_download_name_matches_the_reserved_file(self, out_root, gen_ok):
        """Content-Disposition 이름이 실제 파일과 어긋나면 사용자는 남의 이름을 본다."""
        V.vcast_generate_excel(_req(output_filename="dup.xlsx"))
        resp = V.vcast_generate_excel(_req(output_filename="dup.xlsx"))
        assert resp.filename == Path(resp.path).name, (resp.filename, resp.path)
        assert resp.filename != "dup.xlsx", "선점됐는데 이름은 원본 그대로다"

    def test_default_name_is_reserved_too(self, out_root, gen_ok, monkeypatch):
        """`output_filename` 이 없을 때(ts 이름)도 같은 초면 부딪힌다."""
        class _FixedClock:
            @staticmethod
            def now():
                import datetime as _dt
                return _dt.datetime(2026, 8, 19, 12, 0, 0)

        monkeypatch.setattr(V, "datetime", _FixedClock)
        a = V.vcast_generate_excel(_req())
        Path(a.path).write_bytes(b"USER-A")
        b = V.vcast_generate_excel(_req())
        assert Path(a.path) != Path(b.path)
        assert Path(a.path).read_bytes() == b"USER-A"


class TestFailedGenerationLeavesNoGhost:
    """선점은 0바이트 파일을 먼저 만든다 — 실패하면 치워야 목록에 유령이 안 뜬다."""

    def test_generator_returning_false_cleans_up(self, out_root, monkeypatch):
        monkeypatch.setattr(V, "generate_testcase_excel", lambda *_a, **_k: False)
        with pytest.raises(HTTPException) as ei:
            V.vcast_generate_excel(_req(output_filename="ghost.xlsx"))
        assert ei.value.status_code == 500
        assert list(out_root.glob("*.xlsx")) == [], "빈 선점 파일이 남았다"

    def test_generator_raising_cleans_up(self, out_root, monkeypatch):
        def _boom(*_a, **_k):
            raise RuntimeError("boom")

        monkeypatch.setattr(V, "generate_testcase_excel", _boom)
        with pytest.raises(HTTPException):
            V.vcast_generate_excel(_req(output_filename="ghost.xlsx"))
        assert list(out_root.glob("*.xlsx")) == [], "빈 선점 파일이 남았다"

    def test_nonempty_output_is_never_removed(self, out_root, monkeypatch):
        """⚠ 정리가 과하면 성공 산출물을 지운다 — 내용이 있으면 손대지 않는다."""
        def _write_then_fail(_b, out_path, _m):
            Path(out_path).write_bytes(b"PARTIAL")
            return False

        monkeypatch.setattr(V, "generate_testcase_excel", _write_then_fail)
        with pytest.raises(HTTPException):
            V.vcast_generate_excel(_req(output_filename="partial.xlsx"))
        left = list(out_root.glob("*.xlsx"))
        assert [p.name for p in left] == ["partial.xlsx"], left


class TestQacHasTheSameDefectAndTheSameFix:
    """⚠ **같은 패턴의 다른 입구** — `/api/qac/generate-excel` 도 클라이언트 `output_filename`
    을 봉인 없이 붙이고 있었다(이쪽은 **쿼리 파라미터**). 같은 파일의 다운로드
    (`qac_download_report`)는 이미 `safe_resolve_under` 를 쓴다 — 같은 비대칭이다.

    한쪽만 고치면 나머지가 다음 라운드에 올라온다. 그래서 두 엔드포인트를 **한 파일에서**
    함께 고정한다.
    """

    @pytest.fixture()
    def qac(self, tmp_path, monkeypatch):
        from backend.routers import qac as Q

        monkeypatch.setattr(Q, "repo_root", tmp_path)
        monkeypatch.setattr(Q, "parse_qac_report", lambda *_a, **_k: object())

        written: list[Path] = []

        def _gen(_mgr, out_path) -> bool:
            written.append(Path(out_path))
            Path(out_path).write_bytes(b"QAC-XLSX")
            return True

        monkeypatch.setattr(Q, "generate_qac_excel", _gen)
        return Q, tmp_path / "reports" / "qac_excel", written

    @staticmethod
    def _call(Q, output_filename):
        import asyncio

        class _FakeUpload:
            filename = "r.html"

            async def read(self):
                return b"<html></html>"

        return asyncio.run(Q.qac_generate_excel(
            file=_FakeUpload(), old_version=False, output_filename=output_filename))

    @pytest.mark.parametrize("rel", ["../../evil.xlsx", "sub/../../../escape.xlsx"])
    def test_relative_escape_is_rejected(self, qac, tmp_path, rel):
        Q, out_dir, written = qac
        target = TestOutputFilenameIsConfined._inside_tmp(tmp_path, out_dir, rel)
        with pytest.raises(HTTPException) as ei:
            self._call(Q, rel)
        assert ei.value.status_code == 400, ei.value.detail
        assert not target.exists(), f"봉인 밖에 파일이 생겼다: {target}"
        assert not written, "봉인 전에 생성기가 돌았다"

    def test_absolute_escape_is_rejected(self, qac, tmp_path):
        Q, _out_dir, written = qac
        target = tmp_path / "qac_abs_escape.xlsx"
        with pytest.raises(HTTPException) as ei:
            self._call(Q, str(target))
        assert ei.value.status_code == 400, ei.value.detail
        assert not target.exists(), f"절대경로로 밖에 썼다: {target}"
        assert not written

    def test_failed_generation_leaves_no_ghost(self, qac, monkeypatch):
        """⚠ 선점은 0바이트 파일을 먼저 만든다 — `/api/qac/reports` 는 디렉터리를 glob 해서
        그대로 보여주므로, 실패분을 안 치우면 **열리지 않는 리포트**가 목록에 쌓인다."""
        Q, out_dir, _written = qac
        monkeypatch.setattr(Q, "generate_qac_excel", lambda *_a, **_k: False)
        with pytest.raises(HTTPException) as ei:
            self._call(Q, "ghost.xlsx")
        assert ei.value.status_code == 500
        assert list(out_dir.glob("*.xlsx")) == [], "빈 선점 파일이 남았다"

    def test_partial_output_is_kept(self, qac, monkeypatch):
        """⚠ 정리가 과하면 진단 근거인 부분 산출물을 지운다 — 크기 0 인 것만 지운다."""
        Q, out_dir, _written = qac

        def _write_then_fail(_mgr, out_path) -> bool:
            Path(out_path).write_bytes(b"PARTIAL")
            return False

        monkeypatch.setattr(Q, "generate_qac_excel", _write_then_fail)
        with pytest.raises(HTTPException):
            self._call(Q, "partial.xlsx")
        assert [p.name for p in out_dir.glob("*.xlsx")] == ["partial.xlsx"]

    def test_normal_name_works_and_is_reserved(self, qac):
        Q, out_dir, _written = qac
        first = self._call(Q, "same.xlsx")
        Path(first.path).write_bytes(b"USER-A")
        second = self._call(Q, "same.xlsx")
        assert Path(second.path) != Path(first.path), "두 요청이 같은 경로를 받았다"
        assert Path(first.path).read_bytes() == b"USER-A", "앞 사용자의 리포트가 덮였다"
        assert second.filename == Path(second.path).name


class TestReadWriteSymmetry:
    """⚠ 구조 가드 — 읽기만 봉인된 상태로 되돌아가지 않게.

    이 엔드포인트의 결함은 "봉인 함수가 없다"가 아니라 **같은 파일에서 읽기에만
    적용돼 있었다**는 것이다. 동작 테스트는 오늘의 경로만 보므로, 쓰기 경로에서
    봉인 호출이 사라지는 회귀는 구조로도 막는다.
    """

    @pytest.mark.parametrize("path,start,end", [
        ("backend/routers/vcast.py", "def vcast_generate_excel(", "def vcast_process_jenkins("),
        ("backend/routers/qac.py", "async def qac_generate_excel(", "@router.get(\"/api/qac/reports\")"),
    ])
    def test_the_write_endpoint_calls_safe_resolve_under(self, path, start, end):
        src = Path(path).read_text(encoding="utf-8")
        body = src[src.index(start):src.index(end)]
        assert "safe_resolve_under(" in body, f"{path}: 쓰기 엔드포인트에서 봉인이 사라졌다"
        assert "reserve_unique_path(" in body, f"{path}: 쓰기 엔드포인트에서 선점이 사라졌다"

    def test_no_raw_join_of_client_filename_remains(self):
        """⚠ **주석을 걷어내고** 본다 — 위 결함을 설명한 주석이 바로 그 문자열을 담고 있어
        원문 전체 검색은 자기 설명에 걸린다(오검출)."""
        src = Path("backend/routers/vcast.py").read_text(encoding="utf-8")
        start = src.index("def vcast_generate_excel(")
        end = src.index("def vcast_process_jenkins(")
        code = [ln for ln in src[start:end].splitlines() if not ln.lstrip().startswith("#")]
        assert code, "함수 본문을 못 찾았다"
        assert not any("output_dir / filename" in ln for ln in code), (
            "클라이언트 파일명을 그대로 join 하는 코드가 돌아왔다")
