"""`fn_id` 충돌로 함수가 **조용히 덮어써지던** 결함의 가드.

## 무엇이 있었나

`generate_uds_source_sections` 는 함수마다 `fn_id = f"SwUFn_{mod_idx:02d}{counter:02d}"`
를 만들고 `function_details[fn_id] = detail` 로 담는다.

- `mod_idx` 는 **SwCom 번호**다(`component_map` 의 `Bootloader(SwCom_35)` → 35).
- 그런데 `counter` 는 **파일 stem 별**로 셌다.

같은 SwCom 에 속한 파일이 여럿이면 서로 다른 함수가 **같은 fn_id** 를 받고, dict 대입이
뒤엣것으로 덮어썼다. 경고도 로그도 없다.

실측(PDS128_FBL, 2026-08-12): `mod_idx=35` 에 파일 11개가 몰려 있었다.

    module_name   함수   첫 fn_id
    linuds         86    SwUFn_3501
    lin            24    SwUFn_3501   ← 충돌
    main            5    SwUFn_3501   ← 충돌

결과: c_parser 186함수 → `function_details` 165개. `main.c` 는 24개 중 **5개만** 살아남고
`Check_MainApp_Jump`·`Copy_Shadow`·`MainServiceLoop`·`Get_RAM_Ptr`·`Jump_Main_Application`
이 사라졌다. 이 함수들은 SUTS/SITS/STS/UDS **모든 산출물에서 통째로 빠진다**.

수정: counter 를 `mod_idx`(SwCom) 단위로 센다 — `SwUFn_{SwCom}{순번}` 체계의 원래 의도다.

⚠ 같은 코드가 **두 곳**(주 경로 + 폴백 경로)에 있다. 한쪽만 고치면 폴백에서 그대로
재발하므로 둘 다 본다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "report_gen" / "uds_generator.py"


def test_counter_is_keyed_by_swcom_not_filename():
    """`counter` 를 파일 stem 으로 세는 형태가 되살아나면 깨진다.

    구조 검사인 이유: 실제 충돌을 재현하려면 같은 SwCom 에 속한 파일이 여럿인 소스
    트리가 필요한데, 그건 합성으로 만들기 어렵고 `component_map` 에도 의존한다.
    대신 **결함의 형태 자체**(module_name 기준 집계)를 막는다.
    """
    body = _SRC.read_text(encoding="utf-8", errors="ignore")
    bad = "counter = sum(1 for r in function_table_rows if r[1] == module_name) + 1"
    assert bad not in body, (
        "counter 를 module_name(파일 stem) 별로 세고 있다 — 같은 SwCom 의 다른 파일과 "
        "fn_id 가 충돌해 function_details 가 조용히 덮어써진다."
    )
    # 두 경로 모두 SwCom 단위 카운터를 써야 한다(한쪽만 고치면 폴백에서 재발).
    assert body.count("_fn_counter_by_mod.get(mod_idx, 0) + 1") == 2, (
        "SwCom 단위 카운터가 두 곳(주 경로·폴백 경로)에 모두 있어야 한다"
    )


def test_fn_id_assignment_never_overwrites_silently():
    """`function_details[fn_id] = detail` 대입이 남아 있다면 fn_id 유일성이 전제다.

    대입 자체는 정상이지만, 그 전제가 깨지면 **조용한 손실**이 된다. 유일성을
    책임지는 카운터가 선언돼 있는지 AST 로 확인한다.
    """
    tree = ast.parse(_SRC.read_text(encoding="utf-8", errors="ignore"))
    declared = any(
        isinstance(n, ast.AnnAssign)
        and isinstance(n.target, ast.Name)
        and n.target.id == "_fn_counter_by_mod"
        for n in ast.walk(tree)
    )
    assert declared, "_fn_counter_by_mod 선언이 없다 — fn_id 유일성을 아무도 책임지지 않는다"


def test_no_function_is_lost_to_id_collision(tmp_path):
    """손실 자체를 관측한다 — 파싱된 함수 수 ≥ 소스에 쓴 함수 수.

    ⚠ 이 테스트는 **충돌 조건을 재현하지 못한다**는 것을 확인했다. 합성 트리에서는
      `component_map` 이 두 파일을 같은 `module_name` 으로 묶어 버려 옛 코드에서도
      counter 가 공유되고, 따라서 충돌이 나지 않는다(옛 코드를 되돌려 넣어도 통과했다).
      충돌은 `module_name`(파일 stem)과 `mod_idx`(SwCom)가 **갈라지는** 실제 트리에서만
      난다 — 실측은 `PDS128_FBL` 에서 165 → 200 함수, `main.c` 5 → 26 개다.

      그래서 이 파일의 실질 가드는 위 두 **구조 검사**이고, 이것은 "그래도 손실이 나면
      잡는다" 는 하한선이다. 통과한다고 충돌이 없다는 뜻은 아니다.
    """
    pytest.importorskip("tree_sitter", reason="c_parser 는 tree-sitter 기반")
    from report_gen import uds_generator as ug

    (tmp_path / "alpha.c").write_text(
        "void a_one(void){int x=1;}\nvoid a_two(void){int y=2;}\n", encoding="utf-8"
    )
    (tmp_path / "beta.c").write_text(
        "void b_one(void){int z=3;}\nvoid b_two(void){int w=4;}\n", encoding="utf-8"
    )
    cmap = {
        "alpha.c": {"component": "Boot(SwCom_35)", "verify": "O", "structure": "FBL"},
        "alpha": {"component": "Boot(SwCom_35)", "verify": "O", "structure": "FBL"},
        "beta.c": {"component": "Boot(SwCom_35)", "verify": "O", "structure": "FBL"},
        "beta": {"component": "Boot(SwCom_35)", "verify": "O", "structure": "FBL"},
    }
    res = ug.generate_uds_source_sections(str(tmp_path), component_map=cmap)
    fd = res.get("function_details") or {}
    names = {str(v.get("name", "")) for v in fd.values() if isinstance(v, dict)}

    for fn in ("a_one", "a_two", "b_one", "b_two"):
        assert fn in names, f"{fn} 이 사라졌다 — fn_id 충돌로 덮어써졌을 가능성"
