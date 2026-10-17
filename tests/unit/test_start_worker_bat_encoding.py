"""`scripts/start_worker.bat` 은 **CP949** 여야 한다 — UTF-8 로 저장하면 조용히 죽는다.

2026-08-19 실측: 이 파일을 UTF-8 로 썼더니 cmd 가 배치 파일을 **OEM 코드페이지**로
파싱하면서 한글 주석 바이트가 깨졌고, 그 여파로 `if (` … `)` 괄호 블록 구조까지
무너져 **스크립트가 통째로 안 돌았다**(에러 메시지가 `'/i' 은(는) 인식할 수 없는…`
같은 형태라 원인이 인코딩이라는 걸 알아보기 어렵다).

저장소의 다른 `.bat`(`start.bat`·`start_frontend.bat`)은 전부 ASCII 라 이 함정에
안 걸렸다. 한글을 쓰는 배치 파일은 이 파일이 처음이므로 여기서 고정한다.

⚠ 이 가드는 **관측 가능한 것**을 단언한다 — "CP949 로 디코딩되는가" 가 아니라
  "UTF-8 로 저장돼 있지 않은가" 까지 본다. 전자만 보면 ASCII 파일도 통과한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BAT = REPO / "scripts" / "start_worker.bat"


@pytest.mark.skipif(not BAT.exists(), reason="start_worker.bat 미배치")
class TestEncoding:
    @staticmethod
    def _raw() -> bytes:
        return BAT.read_bytes()

    def test_has_non_ascii_content(self):
        """한글이 사라졌다면 누군가 메시지를 지운 것 — 그럼 이 가드의 전제가 깨진다."""
        assert any(b > 127 for b in self._raw()), (
            "비-ASCII 가 없다. 한글 안내를 지웠다면 이 테스트도 함께 정리할 것"
        )

    def test_decodes_as_cp949(self):
        raw = self._raw()
        try:
            txt = raw.decode("cp949")
        except UnicodeDecodeError as exc:
            pytest.fail(f"CP949 로 못 읽는다 — cmd 가 파싱에 실패한다: {exc}")
        assert "CLOUDIUM_WORKER_PORT" in txt

    def test_is_not_utf8(self):
        """UTF-8 로 저장되면 cmd 파싱이 깨진다. **이게 실제로 일어났던 결함이다.**"""
        with pytest.raises(UnicodeDecodeError):
            self._raw().decode("utf-8")

    def test_no_chars_outside_cp949(self):
        """em dash(—)·⚠ 같은 글자는 CP949 에 없다. 넣으면 저장 자체가 안 된다."""
        txt = self._raw().decode("cp949")
        bad = sorted({c for c in txt if not _cp949_ok(c)})
        assert not bad, f"CP949 로 표현 못 하는 글자: {bad}"


def _cp949_ok(ch: str) -> bool:
    try:
        ch.encode("cp949")
    except UnicodeEncodeError:
        return False
    return True


class TestGitattributesKeepsCrlf:
    """cmd 는 CRLF 를 기대한다. `.gitattributes` 가 `.bat` 을 덮는지 본다.

    작업 트리의 줄바꿈을 직접 보지 않는 이유: checkout 규칙이 그걸 결정하므로
    **규칙 쪽을 단언**해야 플랫폼과 무관하게 성립한다.
    """

    def test_bat_declared_crlf(self):
        ga = (REPO / ".gitattributes").read_text(encoding="utf-8", errors="replace")
        lines = [ln.strip() for ln in ga.splitlines()
                 if ln.strip().startswith("*.bat") or ln.strip().startswith("*.cmd")]
        assert lines, ".gitattributes 에 *.bat 규칙이 없다 — checkout 시 LF 로 정규화될 수 있다"
        assert any("eol=crlf" in ln for ln in lines), f"eol=crlf 가 아니다: {lines}"
