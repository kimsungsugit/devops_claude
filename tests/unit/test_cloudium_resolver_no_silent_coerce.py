"""Cloudium resolver — 형식 불일치를 빈 값으로 접지 않는다 (2026-08-04).

## 왜 생겼나

`read_bytes` 는 W5 수정에서 **비정상 응답을 명시 오류로 올리도록** 고쳐졌다:

    if not isinstance(resp, dict):
        raise PermissionError("... 응답 형식 비정상 ...")

그런데 **형제 둘은 옛 계약 그대로였다**:

    read_text : return result if isinstance(result, str)  else ""
    list_dir  : return list(result) if isinstance(result, list) else []

worker 가 result 를 안 주거나(구버전·미지원 op) 이상한 형을 주면 호출자에게는
"빈 파일" / "빈 폴더" 로 보인다 — **읽기 실패와 빈 내용이 구분 불가**. 이 저장소의
1순위 재발 패턴(같은 결함을 한쪽만 고침)이라 셋을 같은 계약으로 맞춘다.

## 이 파일이 **주장하지 않는** 것

`list_dir` 가 **없는 폴더**에 `[]` 를 주는 문제는 여기서 안 고친다. 그건 worker 가
정상 응답(빈 list)을 준 경우이고 `LocalFileResolver` 도 동일하게 동작하므로,
한쪽만 바꾸면 모드 간 계약이 갈린다. 아래 `test_empty_list_is_still_empty` 가
**현 계약을 명시적으로 못 박아** 나중에 바꿀 때 이 파일이 함께 갱신되게 한다.
"""
from __future__ import annotations

import pytest

pytest.importorskip("backend.services.file_resolver")

from backend.services import file_resolver  # noqa: E402
from backend.services.file_resolver import CloudiumFileResolver  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_bypasses(monkeypatch, tmp_path):
    """workspace/home bypass 를 tmp_path 밖으로 밀어낸다.

    ⚠ 이게 없으면 **차단 테스트가 조용히 무의미해진다.** 이 저장소의 pytest
      basetemp 는 `<repo>/.codex_tmp/...` 이고 `_PROJECT_ROOT` 는 repo 라서,
      `_check_allowed` 가 화이트리스트를 **보기도 전에** workspace bypass 로
      통과시킨다. `_USER_HOME` 도 같은 이유로 함께 밀어낸다(기본 temp 는
      `C:/Users/<user>/AppData/...` 라 홈 하위다).
      실측: 이 fixture 없이 쓴 차단 테스트 4건이 전부 `DID NOT RAISE` 였다.
    """
    monkeypatch.setattr(file_resolver, "_PROJECT_ROOT", tmp_path / "_isolated_root")
    monkeypatch.setattr(file_resolver, "_USER_HOME", tmp_path / "_isolated_home")


@pytest.fixture
def resolver(monkeypatch, tmp_path):
    """게이트/화이트리스트는 통과시키고 IPC 응답만 조작한다."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    return CloudiumFileResolver(allowed_prefixes=str(tmp_path))


def _stub_ipc(monkeypatch, resolver, value):
    monkeypatch.setattr(type(resolver), "_ipc_call",
                        lambda self, op, args=None, timeout=10.0: value)


# ---------------------------------------------------------------------------
# read_text
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bogus", [None, 123, {"data": "x"}, [], b"bytes"])
def test_read_text_rejects_non_string_response(monkeypatch, resolver, tmp_path, bogus):
    _stub_ipc(monkeypatch, resolver, bogus)
    with pytest.raises(PermissionError, match="read_text 응답 형식 비정상"):
        resolver.read_text(str(tmp_path / "a.txt"))


def test_read_text_passes_through_real_string(monkeypatch, resolver, tmp_path):
    _stub_ipc(monkeypatch, resolver, "hello")
    assert resolver.read_text(str(tmp_path / "a.txt")) == "hello"


def test_read_text_empty_string_is_not_an_error(monkeypatch, resolver, tmp_path):
    """진짜 빈 파일은 정상이다 — 과잉 차단하면 멀쩡한 흐름이 깨진다."""
    _stub_ipc(monkeypatch, resolver, "")
    assert resolver.read_text(str(tmp_path / "a.txt")) == ""


# ---------------------------------------------------------------------------
# list_dir
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bogus", [None, "a,b", 0, {"files": []}])
def test_list_dir_rejects_non_list_response(monkeypatch, resolver, tmp_path, bogus):
    _stub_ipc(monkeypatch, resolver, bogus)
    with pytest.raises(PermissionError, match="list_dir 응답 형식 비정상"):
        resolver.list_dir(str(tmp_path))


def test_list_dir_passes_through_real_list(monkeypatch, resolver, tmp_path):
    _stub_ipc(monkeypatch, resolver, ["x.docx", "y.xlsm"])
    assert resolver.list_dir(str(tmp_path)) == ["x.docx", "y.xlsm"]


def test_empty_list_is_still_empty(monkeypatch, resolver, tmp_path):
    """현 계약 못 박기 — worker 가 정상적으로 빈 list 를 주면 `[]` 다.

    ⚠ 이 계약은 '빈 폴더' 와 '없는 폴더' 를 구분하지 못한다(실측 확인). 바꾸려면
      `LocalFileResolver` 와 **함께** 바꿔야 하므로, 그때 이 테스트가 실패해서
      한쪽만 고치는 것을 막는다.
    """
    _stub_ipc(monkeypatch, resolver, [])
    assert resolver.list_dir(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# browse_file / browse_directory
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("op", ["browse_file", "browse_directory"])
@pytest.mark.parametrize("bogus", [None, 0, [], {"path": "x"}])
def test_browse_rejects_non_string_response(monkeypatch, resolver, op, bogus):
    """⚠ **이건 2026-08-05 에 뒤늦게 추가됐다.** 앞선 라운드에서 read_bytes/read_text/
    list_dir 셋을 같은 계약으로 맞추면서 browse 둘을 빠뜨렸다 — 같은 파일 안에서
    '판정 복제 → 한쪽만 고쳐짐' 을 스스로 재현한 셈이다.

    browse 에서 특히 나쁜 이유: 빈 문자열이 **취소** 를 뜻한다(health.py 가
    `error="cancelled"` 로 읽는다). 비정상 응답을 `""` 로 접으면 "worker 가 이 op 을
    모른다" 가 "사용자가 취소했다" 로 둔갑해, 관리자가 원인을 영영 못 본다.
    """
    _stub_ipc(monkeypatch, resolver, bogus)
    with pytest.raises(PermissionError, match=f"{op} 응답 형식 비정상"):
        getattr(resolver, op)("제목", "")


@pytest.mark.parametrize("op", ["browse_file", "browse_directory"])
def test_browse_empty_string_still_means_cancelled(monkeypatch, resolver, op):
    """진짜 취소(빈 문자열)는 그대로 통과해야 한다 — 과잉 차단이면 취소가 오류가 된다."""
    _stub_ipc(monkeypatch, resolver, "")
    assert getattr(resolver, op)("제목", "") == ""


@pytest.mark.parametrize("op", ["browse_file", "browse_directory"])
def test_browse_passes_through_real_path(monkeypatch, resolver, op):
    _stub_ipc(monkeypatch, resolver, "U:/a/b.docx")
    assert getattr(resolver, op)("제목", "") == "U:/a/b.docx"


def test_all_five_ipc_readers_share_one_contract():
    """다섯 IPC 판독기가 **같은 계약**인지 소스에서 직접 센다.

    셋만 고치고 둘을 남기는 일이 실제로 있었으므로, 개수를 세는 가드를 둔다.
    """
    import ast
    from pathlib import Path

    src = Path(file_resolver.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    expected = {"read_bytes", "read_text", "list_dir", "browse_file", "browse_directory"}
    guarded = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in expected:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Raise) and "응답 형식 비정상" in ast.unparse(sub):
                guarded.add(node.name)
    missing = expected - guarded
    assert not missing, (
        f"IPC 판독기 {sorted(missing)} 가 비정상 응답을 빈 값으로 접는다 — "
        "나머지와 계약이 갈렸다"
    )


def test_read_bytes_contract_is_the_reference(monkeypatch, resolver, tmp_path):
    """셋이 같은 계약인지 — read_bytes 가 원본이다."""
    _stub_ipc(monkeypatch, resolver, 42)
    with pytest.raises(PermissionError, match="응답 형식 비정상"):
        resolver.read_bytes(str(tmp_path / "a.bin"))


# ---------------------------------------------------------------------------
# 차단 로그가 허용목록 전체를 덤프하지 않는다
# ---------------------------------------------------------------------------
def test_block_warning_does_not_dump_whole_allowlist(monkeypatch, caplog, tmp_path):
    """실측: 허용목록 54항목 ≈ 5KB/건. 폴더 스캔 한 번에 로그가 수백 KB로 불어난다."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    allowed = [str(tmp_path / f"allowed_{i}" / "deep" / "deeper") for i in range(40)]
    r = CloudiumFileResolver(allowed_prefixes=",".join(allowed))

    with caplog.at_level("WARNING"):
        with pytest.raises(PermissionError):
            r.check_access(str(tmp_path / "elsewhere" / "x.docx"))

    blocked = [rec.getMessage() for rec in caplog.records if "BLOCKED" in rec.getMessage()]
    assert blocked, "차단이 로그에 남아야 한다 — 조용히 막으면 진단이 불가능하다"
    msg = blocked[0]
    assert "allowed_0" not in msg or msg.count("allowed_") <= 1, (
        "허용목록을 통째로 찍고 있다 — 항목 수만 알리고 최근접 1건만 보여야 한다"
    )
    assert "40" in msg, "허용목록 규모(건수)는 남아야 판단이 된다"


def test_block_warning_shows_nearest_prefix(monkeypatch, caplog, tmp_path):
    """실무의 차단은 대개 '형제 폴더라 한 단계가 안 맞음' 이다 — 그걸 보여준다.

    ⚠ **최근접이 목록 첫 항목이면 안 된다.** 그렇게 쓰면 "그냥 첫 항목을 찍는"
      구현도 통과한다(뮤테이션 M15 가 이 구멍으로 살아남았다). 그래서 무관한
      항목을 **앞**에 둔다.
    """
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    far = tmp_path / "zz_unrelated"
    near = tmp_path / "proj" / "docs" / "SwUDS"
    # ⚠ 중간 깊이 항목(`tmp_path/proj`)을 넣으면 **그게 대상 경로를 허용해 버려**
    #   차단 자체가 안 난다(첫 판에서 그 실수를 했고 병렬 실행에서 드러났다).
    #   최근접을 첫 항목이 아니게 만들려면 **허용하지 않는** 항목을 앞에 둬야 한다.
    r = CloudiumFileResolver(allowed_prefixes=f"{far},{near}")

    with caplog.at_level("WARNING"):
        with pytest.raises(PermissionError):
            r.check_access(str(tmp_path / "proj" / "docs" / "Released" / "v2.docx"))

    msg = next(m for m in (rec.getMessage() for rec in caplog.records) if "BLOCKED" in m)
    assert "SwUDS" in msg, (
        f"최근접(공통 3단계)이 아니라 다른 항목을 골랐다 — 첫 항목/얕은 항목을 "
        f"찍는 구현이면 이 단언이 실패해야 한다: {msg}"
    )
    assert "zz_unrelated" not in msg, "무관한 항목이 나오면 최근접 힌트의 의미가 없다"


def test_nearest_prefix_is_diagnostic_only(monkeypatch, tmp_path):
    """최근접 계산이 **경계 판정에 새어들면** 안 된다 — 가까워도 차단이다."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    allowed = tmp_path / "a" / "b" / "c"
    r = CloudiumFileResolver(allowed_prefixes=str(allowed))
    # 4단계 중 3단계가 같다 = 최근접이 매우 가깝다. 그래도 통과하면 안 된다.
    with pytest.raises(PermissionError):
        r.check_access(str(tmp_path / "a" / "b" / "OTHER" / "x"))


def test_nearest_prefix_handles_no_common_segment(monkeypatch, tmp_path):
    """공통 접두가 하나도 없어도 죽지 않는다(진단 코드가 요청을 죽이면 안 된다)."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    r = CloudiumFileResolver(allowed_prefixes="Z:/completely/elsewhere")
    with pytest.raises(PermissionError, match="허용되지 않은 경로"):
        r.check_access(str(tmp_path / "x.docx"))


def test_nearest_prefix_empty_allowlist_does_not_crash(monkeypatch):
    """allowed_prefixes 가 비면 별도 분기(deny-by-default)로 가야 하고, 거기서도
    최근접 계산이 호출돼선 안 된다 — 빈 목록에 대한 max() 류 크래시 방지."""
    monkeypatch.setattr(file_resolver, "is_gate_running", lambda *_a, **_k: True)
    r = CloudiumFileResolver(allowed_prefixes="")
    with pytest.raises(PermissionError, match="allowed_prefixes 미설정"):
        r.check_access("Z:/anything/x.docx")
    assert r._nearest_allowed_prefix("z:/anything/x.docx") == ""
