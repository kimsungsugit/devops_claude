"""요구사항 문서 탈락 사유를 버리지 않는다 (2026-08-05).

## 왜 생겼나

UDS/STS 생성 핸들러 **세 곳**이 전부 이렇게 읽고 있었다::

    try:
        p = Path(path_str).expanduser().resolve()
        if not p.exists() or not p.is_file():
            continue
        text = _read_text_from_file(p)
    except Exception:
        continue

①경로 오타 ②파일 없음 ③**권한 없음** ④본문 추출 0자 가 전부 같은 "그냥 건너뜀"이다.

실측(2026-08-05, 이 머신 · cloudium 모드)으로 확인한 결과 이건 이론이 아니다 —
`config/scm_registry.json` 의 linked_docs **30건이 전부 `U:/…`** 인데:

    Path("U:/…/SRS.docx").exists()   → PermissionError (0.1ms)
    _read_text_from_file(같은 경로)   → "" (빈 문자열)

즉 등록된 SRS/SDS 를 그대로 넘겨도 전량 탈락하고, jenkins STS 핸들러는 끝에서
`"SRS document is required"` 라는 **원인과 무관한** 400 을 낸다. 문서를 준
사용자가 "문서를 달라" 는 말을 듣는다.

## 이 파일이 주장하지 않는 것

정본 해법은 worker IPC 경유 read 로의 이관이다(SwUT/SwIT 계열은 이미 그렇게 한다).
여기서는 **읽기 방식을 바꾸지 않는다** — 무엇이 왜 탈락했는지를 호출자가 사용자에게
전달할 수 있게만 만든다. 이관은 별건이고 생성 입력 경로 전체를 건드리므로
end-to-end 검증 없이 하지 않는다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

pytest.importorskip("backend.services.resolver_helpers")

from backend.services import resolver_helpers as rh  # noqa: E402


def test_missing_file_says_missing(tmp_path):
    p, text, reason = rh.read_requirement_doc(str(tmp_path / "nope.docx"))
    assert text == ""
    assert "파일 없음" in reason


def test_directory_is_not_confused_with_missing(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    _p, text, reason = rh.read_requirement_doc(str(d))
    assert text == ""
    assert "디렉터리" in reason, f"디렉터리인데 다른 사유가 나왔다: {reason}"


def test_permission_error_is_distinguished_from_missing(tmp_path, monkeypatch):
    """**이 라운드의 핵심.** 권한 실패가 '파일 없음'과 같은 말이 되면 안 된다.

    cloudium 모드에서 U: 문서를 열면 실제로 여기 온다(실측: PermissionError 0.1ms).
    사유에 조치 방법(worker 경유 미지원)이 들어 있어야 사용자가 다음 행동을 안다.
    """
    target = tmp_path / "SRS.docx"
    target.write_text("x", encoding="utf-8")
    real_exists = Path.exists

    def _boom(self, *a, **k):
        if self.name == "SRS.docx":
            raise PermissionError("access denied")
        return real_exists(self, *a, **k)

    monkeypatch.setattr(Path, "exists", _boom)
    _p, text, reason = rh.read_requirement_doc(str(target))

    assert text == ""
    assert "권한" in reason, f"권한 실패가 사유로 안 나왔다: {reason}"
    assert "cloudium" in reason.lower(), (
        f"조치 힌트가 없다 — 사용자가 뭘 해야 할지 모른다: {reason}"
    )
    assert "파일 없음" not in reason, "권한 실패를 '파일 없음'으로 보고했다"


def test_empty_body_is_reported_not_silently_dropped(tmp_path, monkeypatch):
    """본문 0자는 '문서를 안 준 것'과 다르다 — 양식/권한 문제일 수 있다."""
    target = tmp_path / "SDS.docx"
    target.write_text("x", encoding="utf-8")
    monkeypatch.setattr("workflow.rag.chunker._read_text_from_file", lambda _p: "")
    _p, text, reason = rh.read_requirement_doc(str(target))
    assert text == ""
    assert "0자" in reason, f"빈 본문을 사유로 안 남겼다: {reason}"


def test_parser_crash_keeps_the_reason(tmp_path, monkeypatch):
    target = tmp_path / "SRS.docx"
    target.write_text("x", encoding="utf-8")

    def _boom(_p):
        raise ValueError("bad zip")

    monkeypatch.setattr("workflow.rag.chunker._read_text_from_file", _boom)
    _p, text, reason = rh.read_requirement_doc(str(target))
    assert text == ""
    assert "ValueError" in reason and "bad zip" in reason


def test_success_returns_text_and_no_reason(tmp_path, monkeypatch):
    target = tmp_path / "SRS.txt"
    target.write_text("  요구사항 본문  ", encoding="utf-8")
    _p, text, reason = rh.read_requirement_doc(str(target))
    assert reason == ""
    assert text == "요구사항 본문", "앞뒤 공백이 정리되지 않았다(호출처가 strip 을 하던 계약)"


def test_allow_gate_runs_before_reading(tmp_path, monkeypatch):
    """범위 게이트는 **본문을 읽기 전에** 평가돼야 한다.

    읽고 나서 검사하면 허용 밖 파일을 먼저 열게 된다 — 순서가 곧 보안 계약이다.
    """
    target = tmp_path / "SRS.docx"
    target.write_text("x", encoding="utf-8")
    read_calls: list[str] = []
    monkeypatch.setattr("workflow.rag.chunker._read_text_from_file",
                        lambda p: (read_calls.append(str(p)), "본문")[1])

    _p, text, reason = rh.read_requirement_doc(str(target), allow=lambda _p: False)
    assert text == ""
    assert "허용" in reason
    assert read_calls == [], "허용되지 않은 파일의 본문을 읽었다 — 게이트가 읽기 뒤에 있다"

    _p2, text2, reason2 = rh.read_requirement_doc(str(target), allow=lambda _p: True)
    assert reason2 == "" and text2 == "본문"


def test_empty_input_is_not_an_error():
    """빈 문자열은 '지정 안 함'이지 실패가 아니다 — 소음을 만들면 안 된다."""
    p, text, reason = rh.read_requirement_doc("")
    assert (p, text, reason) == (None, "", "")


# ---------------------------------------------------------------------------
# 세 호출처가 **모두** 이 헬퍼를 쓰는지 (판정 복제 방지)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rel", ["backend/routers/jenkins.py", "backend/routers/local.py"])
def test_routers_use_the_shared_reader(rel):
    src = (REPO / rel).read_text(encoding="utf-8")
    assert "read_requirement_doc(" in src, f"{rel}: 공용 판독기를 쓰지 않는다"


def test_no_silent_requirement_loop_remains():
    """`except Exception` 으로 요구사항 문서 루프를 삼키는 자리가 남아 있는지.

    세 곳 중 하나만 고치면 나머지가 조용히 옛 동작으로 남는다 — 이 저장소가
    반복해 겪은 형태라 구조로 막는다.
    """
    offenders: list[str] = []
    for rel in ("backend/routers/jenkins.py", "backend/routers/local.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
            if "req_paths_list" not in ast.unparse(node.iter):
                continue
            body = ast.unparse(node)
            # ⚠ req_paths_list 를 도는 루프가 전부 '문서 본문 읽기'는 아니다 —
            #   SDS 파티션 맵 추출처럼 경로만 쓰는 루프도 있다. 본문을 읽는
            #   루프(_read_text_from_file 호출)만 대상으로 좁힌다. 안 그러면
            #   무관한 루프까지 잡는 소음이 되어 곧 무시된다.
            if "_read_text_from_file" not in body:
                continue
            if "read_requirement_doc" not in body:
                offenders.append(f"{rel}:{node.lineno} — 문서 읽기 루프가 공용 판독기를 안 쓴다")
    assert not offenders, "\n  ".join(offenders)
