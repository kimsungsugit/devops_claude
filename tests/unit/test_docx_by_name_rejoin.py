"""`function_details_by_name` 이 `function_details` 와 갈라지던 것 (계획서 후보 21 / C2).

## 결함

payload 는 두 맵을 **둘 다** 싣는다(`jenkins.py:2529` · `local.py:967`·`:1457` ·
`backend/helpers/uds.py:1711` — 4개 빌더 전부). 라우터에서는 같은 dict 객체를
가리키지만, docx 생성은 `_run_docx_in_subprocess`(`backend/helpers/uds.py:1277`)가
payload 를 **JSON 파일로 써서 서브프로세스에 넘기므로** 역직렬화 시점에 갈라진다.

그 뒤 해석 루프(주석-ASIL 승격 · SDS 주입 · `req_map` · 모듈 ASIL 상속)는
`function_details` **전용**인데, 렌더러 `_resolve_function_info` 는
`function_details_by_name` 을 **먼저** 조회한다(키는 양쪽 다 소문자라 적중한다).
→ 렌더러가 **enrich 되지 않은 사본**을 그린다. 예외도 경고도 없다.

## 왜 빌더를 직접 안 부르나

처음엔 `generate_uds_docx` 를 그대로 호출해 payload 상태를 관찰하려 했는데
**단위 테스트로 못 쓴다** — python-docx 표 순회에서 25초 타임아웃을 넘겼다.
그래서 규칙을 `rejoin_function_maps` 라는 이름 있는 함수로 뽑았고, 빌더는 그걸
호출한다. 여기 테스트는 **그 실제 함수**를 태운다(규칙을 재구현하지 않는다).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from report_gen.docx_builder import rejoin_function_maps  # noqa: E402


def _roundtrip() -> tuple[dict, dict]:
    """라우터가 만드는 모양 그대로 두 맵을 싣고 JSON 왕복시킨다.

    왕복 없이 dict 를 그대로 쓰면 파이썬이 같은 객체를 유지해 **결함이 재현되지 않는다** —
    그러면 이 테스트는 통과하지만 아무것도 검증하지 못한다.
    """
    fd = {
        "SwUFn_01": {"id": "SwUFn_01", "name": "Motor_Init", "asil": "", "description": ""},
        "SwUFn_02": {"id": "SwUFn_02", "name": "Motor_Stop", "asil": "", "description": ""},
    }
    by_name = {str(v["name"]).lower(): v for v in fd.values()}
    assert by_name["motor_init"] is fd["SwUFn_01"], "라우터 시점엔 같은 객체여야 한다"
    p = json.loads(json.dumps({"function_details": fd, "function_details_by_name": by_name}))
    return p["function_details"], p["function_details_by_name"]


class TestPremise:
    def test_json_roundtrip_really_splits_the_maps(self):
        """전제 확인 — 왕복이 실제로 객체를 가른다(아니면 이 파일 전체가 무의미)."""
        fd, bn = _roundtrip()
        assert bn["motor_init"] is not fd["SwUFn_01"]


class TestRejoin:
    def test_enrichment_on_function_details_becomes_visible_to_by_name(self):
        """핵심 계약 — 해석 루프가 채운 값이 렌더러(by_name)에 보여야 한다."""
        fd, bn = _roundtrip()
        fd["SwUFn_01"]["asil"] = "D"                 # 해석 루프가 채웠다고 가정
        fd["SwUFn_01"]["asil_source"] = "comment"

        assert bn["motor_init"].get("asil") == "", "전제: 재결합 전엔 안 보인다"
        n = rejoin_function_maps(fd, bn)

        assert n == 2
        assert bn["motor_init"] is fd["SwUFn_01"]
        assert bn["motor_init"]["asil"] == "D"
        assert bn["motor_init"]["asil_source"] == "comment"

    def test_later_writes_are_seen_by_both(self):
        """재결합 **이후**의 변경도 양쪽에 보여야 한다(1회 복사가 아니라 동일 객체)."""
        fd, bn = _roundtrip()
        rejoin_function_maps(fd, bn)
        fd["SwUFn_02"]["related"] = "SwFn_09"
        assert bn["motor_stop"]["related"] == "SwFn_09"

    def test_by_name_only_entries_are_not_dropped(self):
        """orphan 을 지우면 렌더러가 찾던 함수가 사라져 결함을 반대 방향으로 만든다."""
        fd, bn = _roundtrip()
        bn["orphan_fn"] = {"id": "", "name": "orphan_fn", "asil": "B"}
        rejoin_function_maps(fd, bn)
        assert bn["orphan_fn"]["asil"] == "B"

    def test_copy_only_values_are_preserved_and_do_not_overwrite(self):
        """사본에만 있던 값은 살리되, 정본 값을 **덮어쓰지는 않는다**."""
        fd, bn = _roundtrip()
        bn["motor_stop"]["description"] = "사본에만 있던 설명"
        bn["motor_stop"]["asil"] = "QM"          # 사본 값 — 덮어쓰면 안 된다
        fd["SwUFn_02"]["asil"] = "A"             # 정본 값이 이긴다

        rejoin_function_maps(fd, bn)

        merged = bn["motor_stop"]
        assert merged["description"] == "사본에만 있던 설명", "사본 값이 유실됐다"
        assert merged["asil"] == "A", "사본이 정본을 덮어썼다 — ASIL 하향 경로가 열린다"

    def test_already_joined_is_a_noop(self):
        """로컬 동기 경로처럼 원래 같은 객체면 아무것도 하지 않는다(경고도 안 낸다)."""
        fd = {"SwUFn_01": {"id": "SwUFn_01", "name": "Motor_Init", "asil": "D"}}
        bn = {"motor_init": fd["SwUFn_01"]}
        assert rejoin_function_maps(fd, bn) == 0

    def test_non_dict_inputs_are_safe(self):
        assert rejoin_function_maps(None, None) == 0
        assert rejoin_function_maps({}, "nope") == 0


class TestWiring:
    """⚠ 규칙만 테스트하면 **배선이 빠져도 통과한다.**

    실제로 그랬다: 위 규칙 테스트는 전부 통과하는데 `generate_uds_docx` 에서 호출문을
    지우는 뮤테이션이 **생존**했다(M1). 규칙은 지켜지는데 아무도 그 규칙을 안 부르는
    상태 — 이 저장소가 반복해 겪은 "가드가 자기 자신을 안 지킨다" 다.

    `generate_uds_docx` 를 실제로 돌려 확인하는 게 이상적이지만 단위 테스트로는 못 쓴다
    (python-docx 표 순회가 25초 타임아웃을 넘겼다). 그래서 **소스 구조**로 못박는다.
    """

    def test_generate_uds_docx_actually_calls_the_rejoin(self):
        import ast

        src = Path(_repo_root / "report_gen/docx_builder.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        target = next(
            (n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name == "generate_uds_docx"),
            None,
        )
        assert target is not None, "generate_uds_docx 를 못 찾았다 — 이 가드가 무력해졌다"

        called = {
            n.func.id
            for n in ast.walk(target)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "rejoin_function_maps" in called, (
            "generate_uds_docx 가 rejoin_function_maps 를 부르지 않는다 — "
            "두 맵이 갈라진 채로 렌더링된다(해석 루프 결과가 문서에 안 나온다)"
        )
