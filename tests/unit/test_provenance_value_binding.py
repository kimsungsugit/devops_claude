"""출처 라벨은 **값이 있을 때만** 붙는다 — 후보 11 잔여.

## 왜 이 파일이 생겼나 (2026-08-04)

`validation.py::_score_for` 는 값 유무를 보지 않고 `description_source` 라벨만 보고
점수를 매긴다. 그래서 값을 건드리지 않고 라벨만 올리는 코드가 있으면 **빈 칸이
0.95(강한 출처) 점수를 받는다** — "근거는 SDS 급인데 내용이 없다" 는 불가능한 상태다.

실측으로 그런 사이트가 3곳 있었다:

| 사이트 | 하던 일 |
|---|---|
| `backend/routers/local.py` HSIS 승격 | 약한 출처면 `description` 을 안 보고 `hsis`(별칭→`sds`) |
| `tools/generate_uds_local.py` 같은 승격 | 동일 |
| `report_gen/requirements.py` SDS 매칭 | 설명이 비고 SDS 에도 설명이 없으면 `sds_match` |

⚠ **디스크 실측 잔여는 0건이었다.** 그렇다고 무해했던 건 아니다 — 막고 있던 게
`docx_builder.py:2175-2180` 의 마지막 되돌림(자리표시자면 `default` 로 강등) **한 겹**
뿐이었다. 안전망 하나에 의존하는 상태와 유입 경로가 없는 상태는 회귀 위험이 다르다.
그래서 유입 쪽을 닫고, 그 사실을 여기서 값으로 잠근다.

⚠ 판정은 `report_gen/provenance.py::has_evidence_value` 단일 출처다. 세 사이트에
리터럴로 다시 적으면 이 저장소가 네 번 겪은 "판정 복제 → 한쪽만 고쳐짐" 이 된다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from report_gen.provenance import PLACEHOLDER_VALUES, has_evidence_value

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestHasEvidenceValue:
    """판정 자체 — `PLACEHOLDER_VALUES` 어휘를 그대로 따른다."""

    @pytest.mark.parametrize("value", ["", "  ", "TBD", "tbd", "N/A", "n/a", "NA", "-", "None", None])
    def test_placeholders_are_not_evidence(self, value):
        assert has_evidence_value(value) is False

    @pytest.mark.parametrize(
        "value",
        ["버저 출력을 제어한다", "Controls the buzzer output", "0", "SwCom_01", "QM"],
    )
    def test_real_values_are_evidence(self, value):
        assert has_evidence_value(value) is True

    def test_vocabulary_is_the_shared_placeholder_set(self):
        """어휘가 `PLACEHOLDER_VALUES` 에서 갈라지면 즉시 깨진다."""
        for placeholder in PLACEHOLDER_VALUES:
            assert has_evidence_value(placeholder) is False

    def test_zero_is_a_value_not_a_placeholder(self):
        """`0`/`False` 를 falsy 라고 자리표시자로 접지 않는다 — ASIL·카운트에서 실값이다."""
        assert has_evidence_value(0) is True
        assert has_evidence_value(False) is True


def _norm_expr(expr: str) -> str:
    """표현식 텍스트를 AST 왕복으로 정규화 — 따옴표 종류·공백 차이를 없앤다.

    ⚠ `ast.unparse` 는 문자열 리터럴을 **작은따옴표**로 정규화한다. 기대값을 소스
    그대로(`'…get("description")'`) 적으면 영원히 불일치한다 — 실제로 한 번 걸렸다.
    """
    return ast.unparse(ast.parse(expr, mode="eval").body)


def _call_arg_names(source: str, func_name: str) -> set[str]:
    """`source` 안에서 `func_name(...)` 호출에 넘긴 인자 표현식 텍스트 집합(정규화)."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if name != func_name:
            continue
        for arg in node.args:
            found.add(ast.unparse(arg))
    return found


class TestEverySiteIsGuarded:
    """세 사이트가 **실제로** 판정을 호출하는지 소스에서 확인한다.

    ⚠ 동작 테스트만 두면 가드를 지워도 통과하는 경로가 생긴다(빈 설명이 안 들어오는
    픽스처면 조용히 초록). 그래서 호출 자체를 값으로 잠근다.
    """

    @pytest.mark.parametrize(
        ("rel_path", "expected_arg"),
        [
            ("backend/routers/local.py", '_fn_info.get("description")'),
            ("tools/generate_uds_local.py", 'info.get("description")'),
            ("report_gen/requirements.py", "desc"),
        ],
    )
    def test_site_calls_has_evidence_value_on_the_description(self, rel_path, expected_arg):
        source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        args = _call_arg_names(source, "has_evidence_value")
        assert _norm_expr(expected_arg) in args, (
            f"{rel_path} 가 `has_evidence_value({expected_arg})` 로 설명 값을 검사하지 않는다 — "
            "라벨만 올리는 경로가 되살아났다"
        )


class TestGenerateUdsLocalShadowTrap:
    """`tools/generate_uds_local.py` 는 `report_gen.*` 를 **import 할 수 없다**.

    모듈 상단(16-18행)이 `sys.path` 최상단에 `D:/Project/devops/260105` 를 밀어넣는데
    그 트리에도 `report_gen/` 패키지가 있다. 실측(2026-08-04):

        report_gen            -> D:\\Project\\devops\\260105\\report_gen\\__init__.py
        report_gen.provenance -> ModuleNotFoundError (파일 없음)
        report_gen.utils      -> 260105 판(576줄), 이 저장소 판은 622줄 — **다른 파일**

    ⚠ 이건 가설이 아니라 **실제로 깨져 있던 배선**이다. `build_function_details_by_name`
    (§6 후보 21 C3, 커밋 `fc246d7` 의 함수명 키 단일화)은 이 저장소 `utils.py:33` 에만
    있어서 `from report_gen.utils import build_function_details_by_name` 이 **ImportError**
    였다 — 그 fix 는 이 도구 경로에서 한 번도 도달한 적이 없다.
    """

    @staticmethod
    def _is_report_gen(dotted: str) -> bool:
        """`report_gen` 패키지만 잡는다.

        ⚠ 접두 매칭(`startswith("report_gen")`)이면 `report_generator` 도 걸린다 —
        그건 **의도된** 260105 의존이다(이 도구는 그 트리를 대상으로 돈다).
        """
        return dotted == "report_gen" or dotted.startswith("report_gen.")

    def test_no_report_gen_module_imports(self):
        source = (REPO_ROOT / "tools/generate_uds_local.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and self._is_report_gen(node.module or "")
        ]
        offenders += [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
            if self._is_report_gen(alias.name)
        ]
        assert offenders == [], (
            f"tools/generate_uds_local.py 가 {offenders} 를 import 한다 — 260105 트리가 "
            "sys.path 최상단이라 실행 시 다른 파일로 해석되거나 ImportError 로 죽는다. "
            "`_load_repo_module(...)` 를 쓸 것"
        )

    @pytest.fixture(autouse=True)
    def _this_repos_report_generator_first(self):
        """단독 실행 순서 의존 제거(R32 실측 — HEAD 대조군에서도 이 파일 단독은 3건 실패).

        도구는 import 시점에 `sys.path[0]` 에 260105 트리를 꽂고 `import report_generator` 를 하는데,
        전체 스위트에선 다른 테스트가 이미 **이 저장소의** `report_generator` 를 올려 둬 캐시가 이긴다.
        단독으로 돌리면 260105 판이 올라오고, 그 판의 `from report_gen import _build_function_info_rows` 가
        이미 캐시된 이 저장소 `report_gen` 에서 실패한다(`_config_reload.py` 머리글의 그 부작용). 전체
        스위트와 같은 전제를 여기서 명시한다 — 근본(도구의 sys.path 변형)은 R33 후보.
        """
        import report_generator  # noqa: F401 — 캐시 선점이 목적
        yield

    @pytest.mark.parametrize("rel_module", ["provenance", "utils"])
    def test_loader_resolves_this_repo(self, rel_module):
        from tools import generate_uds_local

        module = generate_uds_local._load_repo_module(rel_module)
        assert (
            Path(module.__file__).resolve()
            == (REPO_ROOT / "report_gen" / f"{rel_module}.py").resolve()
        )

    def test_name_map_ssot_is_actually_reachable(self):
        """후보 21 C3 배선이 이 파일에서 **실제로 호출 가능**한지 값으로 확인한다.

        예전엔 함수 안 `from report_gen.utils import …` 라 이 지점에서 ImportError 가
        났고, 그 사실이 어디에도 안 남았다(호출자가 없어 조용했다).
        """
        from tools import generate_uds_local

        by_name = generate_uds_local.build_function_details_by_name(
            {"SwUFn_0001": {"name": "G_Ap_BuzzerCtrl_Func", "description": "x"}}
        )
        assert "g_ap_buzzerctrl_func" in by_name, "함수명 키가 소문자로 정규화되지 않았다"


class TestRequirementsSdsMatchNeedsAValue:
    """`report_gen/requirements.py` — 설명이 비면 `sds_match` 를 안 붙인다."""

    def _run(self, description: str, sds_description: str | None):
        from report_gen import requirements

        info = {"name": "g_ap_buzzerctrl_func", "description": description, "description_source": "inference"}
        sds_info = {"name": "g_ap_buzzerctrl_func"}
        if sds_description is not None:
            sds_info["description"] = sds_description
        # 대상 분기만 재현한다 — 상위 루프는 SDS 문서 로딩이 필요해 단위 검증에 부적합.
        desc = str(info.get("description") or "").strip()
        if (not desc or desc.lower().startswith("function")) and sds_info.get("description"):
            info["description"] = sds_info["description"]
            info["description_source"] = "sds"
        elif (
            requirements.has_evidence_value(desc)
            and str(info.get("description_source") or "").strip() in {"", "inference"}
        ):
            info["description_source"] = "sds_match"
        return info

    def test_empty_description_keeps_inference(self):
        info = self._run("", sds_description=None)
        assert info["description_source"] == "inference"

    def test_placeholder_description_keeps_inference(self):
        info = self._run("TBD", sds_description=None)
        assert info["description_source"] == "inference"

    def test_real_description_gets_sds_match(self):
        info = self._run("버저 출력을 제어한다", sds_description=None)
        assert info["description_source"] == "sds_match"

    def test_sds_description_still_wins(self):
        info = self._run("", sds_description="SDS 원문 설명")
        assert info["description"] == "SDS 원문 설명"
        assert info["description_source"] == "sds"


class TestEmptyValueNeverScoresAsStrongSource:
    """끝단 계약 — 빈 값에 강한 출처가 붙는 조합이 만들어지지 않고, 만들어져도 **강한 점수를 받지 않는다**.

    유입 3곳을 닫았으므로 남은 위험은 '누가 새로 만드는 것'이었고, 그 마지막 층을 R32 가 닫았다:
    `_score_for` 가 값 유무를 본다(`_effective_src` — 값이 자리표시자면 출처 라벨과 무관하게 `default` 0.30).

    ⚠ 예전 이 클래스는 "`_score_for` 는 바꾸지 않았다 — 값 유무를 반영하면 ASIL·Related 가 둘 다 없는 함수를
    D→A 로 **승격**시킨다(방향이 반대)" 로 현행을 잠가 두었다. 그 우려는 **빈 필드를 평균에서 빼는 구현**에
    대한 것이고, R32 는 빈 값을 최저점으로 넣으므로 방향은 하향뿐이다 — 라이브 payload 17,027함수 전수:
    상향 **0** · 하향 52 · 동일 16,975(리포트 71개 재채점: 6개 ≤0.003 하락, 등급 이동 0).
    """

    def test_score_sees_value_presence_and_never_promotes(self, tmp_path):
        """빈 값은 강한 라벨이 붙어 있어도 0.30 — 라벨만 보던 옛 식보다 **높아질 수 없다**."""
        import re

        from report_gen.validation import generate_asil_related_confidence_report

        def _score(payload, name):
            out = tmp_path / f"{name}.md"
            generate_asil_related_confidence_report(payload, str(out))
            m = re.search(r"Overall confidence score: `([\d.]+)` \(grade: `([A-D])`\)", out.read_text(encoding="utf-8"))
            assert m, out.read_text(encoding="utf-8")[:400]
            return float(m.group(1)), m.group(2)

        strong_empty = {"function_details_by_name": {"f": {
            "id": "SwUFn_01", "name": "f",
            "description": "Reads sensor", "description_source": "sds",
            "asil": "", "asil_source": "sds",
            "related": "", "related_source": "sds",
        }}}
        score, grade = _score(strong_empty, "empty")
        # 라벨만 보면 (0.95×3)/3 = 0.95 → A. 값을 보면 (0.95+0.30+0.30)/3 = 0.517 → D.
        assert score == pytest.approx(0.517, abs=1e-3)
        assert grade == "D"
        # 값이 있으면 라벨 점수 그대로 — 새 규칙은 값 없는 칸만 내린다(0.95×3/3 은 부동소수로 0.9499… → B).
        full = {"function_details_by_name": {"f": {**strong_empty["function_details_by_name"]["f"], "asil": "B", "related": "SwFn_01"}}}
        full_score, full_grade = _score(full, "full")
        assert full_score == pytest.approx(0.95, abs=1e-3)
        assert full_grade in {"A", "B"}

    def test_the_value_check_lives_in_the_effective_source_helper(self):
        """구조 잠금 — 값 유무 판정은 `_effective_src` 한 곳(표·분포·근거·점수가 같이 쓴다)."""
        import report_gen.validation as validation

        source = Path(validation.__file__).read_text(encoding="utf-8")
        idx = source.index("def _effective_src(info: Dict[str, Any], field_name: str) -> str:")
        body = source[idx: idx + 1600]
        assert "has_evidence_value(info.get(field_name))" in body
        assert "unrecorded_source(info.get(field_name))" in body
