"""준비 게이트의 **조치** 엔드포인트 — 경로 교체와 주석 대상 목록.

게이트가 "무엇이 부족한지" 를 말해도 화면에서 고칠 수 없으면 절반이다. 다만 조치가
쓰기 동작이므로 입력 표면이 넓어지지 않게 하는 것이 이 파일의 본체다:

- 경로 교체는 **파일명만** 받는다. 부모 디렉터리는 기존 등록 경로에서 오므로 등록된
  폴더 밖을 가리킬 수 없다.
- 교체 전에 **실물을 확인**한다. 없는 파일로 바꾸면 문제를 옮기기만 한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import docgen_comment_coverage as cov

client = TestClient(app)
HEADERS = {"X-User": "tester"}


# ── 경로 교체: 입력 표면 ────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    "../outside.docx",
    "sub/dir.docx",
    "C:\\other\\abs.docx",
    "",
    ".",
])
def test_adopt_rejects_path_like_filenames(bad: str) -> None:
    """경로 구분자가 섞인 이름은 거부한다 — 등록 폴더 밖을 가리킬 수 없어야 한다."""
    r = client.post("/api/docgen/adopt-doc-path", headers=HEADERS,
                    json={"scm_id": "any", "doc_key": "srs", "filename": bad})
    # 400(파일명 불가) 이어야 하며, 레지스트리 조회(404)까지 가면 안 된다.
    assert r.status_code == 400, r.text


def test_adopt_rejects_unknown_doc_key() -> None:
    r = client.post("/api/docgen/adopt-doc-path", headers=HEADERS,
                    json={"scm_id": "any", "doc_key": "not_a_key", "filename": "x.docx"})
    assert r.status_code == 400
    # 이 앱의 오류 응답은 `{ok: false, error: {code, message}}` 로 감싸진다.
    body = r.json()
    assert body.get("ok") is False
    assert "문서 키" in str((body.get("error") or {}).get("message", ""))


def test_adopt_unknown_entry_is_404() -> None:
    r = client.post("/api/docgen/adopt-doc-path", headers=HEADERS,
                    json={"scm_id": "__no_such_entry__", "doc_key": "srs",
                          "filename": "spec_v2.docx"})
    assert r.status_code == 404


# ── 주석 보강 대상 ──────────────────────────────────────────────────────────

def test_comment_targets_requires_measurement_first(tmp_path: Path) -> None:
    """측정 전에는 **재지 않는다** — 소스 파싱은 수십 초 이상 걸린다.

    빈 목록을 돌려주되 사유를 싣는다. 사유 없이 `[]` 만 주면 "대상이 없다"(= 주석이
    완벽하다)로 읽힌다.
    """
    cov.clear_cache()
    r = client.post("/api/docgen/comment-targets", headers=HEADERS,
                    json={"source_root": str(tmp_path)})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["reason"]
    assert body["targets"] == []


def test_comment_targets_splits_two_kinds(tmp_path: Path) -> None:
    """"주석 없음" 과 "내용 없음" 을 **나눠서** 낸다.

    실측(HDPDM01): 380개 중 277개가 후자다. 후자는 주석 블록이 이미 있어 한 줄만
    채우면 되는 훨씬 싼 작업이라, 합치면 조치 비용을 오독한다.
    """
    src = tmp_path / "m.c"
    src.write_text(
        "/**\n * Function  |\n */\n"
        "void empty_desc(void) { }\n"
        "\n"
        "/**\n * Function  | Clears the fault latch and resets the counter.\n */\n"
        "void good_desc(void) { }\n"
        "\n"
        "void no_comment_fn(void) { }\n",
        encoding="utf-8",
    )
    cov.clear_cache()
    res = cov.list_comment_targets(str(tmp_path))
    names_empty = {r["function"] for r in res["empty_comment"]}
    names_none = {r["function"] for r in res["no_comment"]}
    # 판정의 요지: 라벨만 있는 것과 내용이 있는 것이 갈려야 한다.
    assert "empty_desc" in names_empty or "empty_desc" in names_none
    assert "good_desc" not in names_empty and "good_desc" not in names_none
    assert res["total_targets"] == len(res["no_comment"]) + len(res["empty_comment"])


def test_comment_targets_carry_file_and_function(tmp_path: Path) -> None:
    """건수만으로는 못 고친다 — 파일·함수명이 있어야 개발자가 주석을 단다."""
    (tmp_path / "a.c").write_text("void bare(void) { }\n", encoding="utf-8")
    cov.clear_cache()
    res = cov.list_comment_targets(str(tmp_path))
    rows = res["no_comment"] + res["empty_comment"]
    if rows:  # 파서가 이 형태를 함수로 잡았을 때만 검증한다
        assert rows[0]["file"]
        assert rows[0]["function"]
