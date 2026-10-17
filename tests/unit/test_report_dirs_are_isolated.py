"""테스트가 **사용자 `reports/` 트리**에 쓰지 않는다 — 격리 표가 실제 코드와 lockstep 인가. (R38 D-1)

## 왜 이 가드가 있나

R36 이 `reports/quality.sqlite` 한 곳에 세션 격리를 넣었는데, **같은 결함이 `reports/` 하위
디렉터리에 그대로 남아** 있었다. 실측(2026-09-08): 전량 실행 1회당 24개 파일이 사용자 트리에
생기고, 누적은 `impact_changes` 11,128 · `impact_audit` 4,906 · `uds` 3,638 · `qac_impact` 1,586
이며 `qac_impact` 는 **1,586개 중 1,585개**가 테스트 산물(실물 1건)이었다.

그 파일들은 조용히 쌓이는 게 아니라 **화면을 갈아치운다**: `build_timeline(scm_id, limit=200)` 이
시각 역순으로 읽기 때문에 픽스처가 최신 200건을 100% 점유했고, HDPDM01 의 실제 영향분석 이력
735건이 화면에서 통째로 사라졌다(`distinct_changed_functions` 9 vs 대조군 821). 그 값은
`ProjectSummarySection.jsx` 가 "배너의 유일한 출처" 라고 적은 경로이고 `summary_insight.py` 가
**AI 인사이트 입력**으로도 읽는다.

## 이 파일이 막는 것

격리 자체는 `tests/conftest.py::_isolate_report_dirs`(세션 autouse)가 한다. 여기서는 **그 표가
비지 않았는지**를 잰다 — 개별 테스트의 `monkeypatch` 47곳이 이미 있었는데 **3파일이 빠져서**
유출이 계속됐다. 손으로 드는 목록은 반드시 빠지므로, 트리를 전수로 걸어 대조한다.

⚠ 이 가드는 만들자마자 실제로 하나를 찾아냈다(`workflow.impact_jobs.JOB_DIR`, 누적 249개).
   감사가 짚은 4개만 넣고 끝냈다면 그 축은 계속 샜을 것이다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from tests.conftest import _REPORT_DIR_TARGETS

_REPO = pathlib.Path(__file__).resolve().parents[2]
#: 스캔 범위 — 프로덕션 코드가 사는 곳. `scripts/oneoff/*` 는 사람이 직접 돌리는 일회성 도구라 뺀다.
_SCAN_ROOTS = ("backend", "workflow", "generators", "report_gen", "tools")
_SKIP_PARTS = {"venv", ".venv", "node_modules", "site-packages", "__pycache__"}

#: 인라인 조립이 남아 있는 곳 — **사유가 있어야 한다**. 목록이 늘면 그만큼 격리가 얇아진다.
#: (R38 이월) `tools/*` 는 사람이 직접 돌리는 CLI 진입점이라 경로가 `argparse` 기본값·출력 인자로
#: 들어 있다. 테스트가 이 모듈들을 import 하기는 하지만(`test_cloudium_impact` ·
#: `test_generate_uds_local` · `test_provenance_value_binding`) 그 경로로 **쓰기까지 가는 호출은
#: 하지 않는다**(전부 파서·헬퍼 단위 호출). 단일 출처로 옮기는 것은 별 라운드.
#: ⚠ 앞판은 이 자리에 "도달하면 이 파일의 파일 수 불변 가드가 먼저 깨진다" 고 적었는데 **그런 가드는
#:   없다**(리뷰 W-2). 사유가 없는 가드를 근거로 들면, 사유 형식만 통과하고 내용은 거짓이 된다 —
#:   `test_the_exception_list_is_not_a_dumping_ground` 가 막으려던 바로 그 형태를 스스로 저질렀다.
#:   실제로 격리를 재는 것은 아래 `TestIsolationActuallyRedirects` 두 건이다.
_INLINE_EXCEPTIONS = {
    "tools.generate_uds_local": "CLI 진입점 — 출력 경로가 인자 기본값",
    "tools.impact_analysis": "CLI 진입점 — `--out` 기본값",
    "tools.validate_uds_constraints": "CLI 진입점 — 검증 대상 경로 기본값",
    # (R39) `backend/reports/uds_local` 을 읽는 일회성 분석 도구들 — 사람이 직접 돌린다.
    # 테스트가 import 하지 않으며(전량 실행 기준), 읽기 위주라 유출 위험이 낮다.
    "tools.compare_suds_template": "CLI 분석 도구 — 산출물 비교(읽기)",
    "tools.report_called_calling_accuracy": "CLI 분석 도구 — 정확도 리포트(읽기)",
    "tools.report_swcom_context": "CLI 분석 도구 — SwCom 문맥 리포트(읽기)",
    "tools.report_swcom_context_regression": "CLI 분석 도구 — 회귀 비교(읽기)",
    "tools.run_manual_uds_generation": "CLI 진입점 — 수동 UDS 생성 출력 경로",
}


def _iter_scanned_files():
    for root in _SCAN_ROOTS:
        for path in (_REPO / root).rglob("*.py"):
            if _SKIP_PARTS & set(path.parts):
                continue
            src = path.read_text(encoding="utf-8", errors="replace")
            if '"reports"' not in src and "'reports'" not in src:
                continue
            try:
                yield path, src, ast.parse(src)
            except SyntaxError:
                continue


def _report_subdir_of(node: ast.AST) -> str | None:
    """`X / "reports" / "sub"` 조립식이면 `"sub"`, 아니면 None."""
    if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)):
        return None
    left = node.left
    if (isinstance(left, ast.BinOp) and isinstance(left.right, ast.Constant)
            and left.right.value == "reports"):
        return node.right.value
    return None


def _module_level_report_dirs() -> dict[tuple[str, str], str]:
    """`reports/<sub>` 를 가리키는 **모듈 최상위 상수** 전수 → `{(모듈경로, 상수명): 하위디렉터리}`.

    `X / "reports" / "Y"` 형태만 잡는다 — set/list 리터럴 안의 `"reports"` 문자열(제외 목록 등)은
    경로가 아니므로 세지 않는다.

    ⚠ 키가 **(모듈, 상수)** 다. 모듈만으로 키를 잡으면 한 모듈에 두 상수가 있을 때 하나가 덮여
    스캔 수가 조용히 줄어든다 — 실제로 `impact_orchestrator` 에 `SUTS_REPORT_DIR`·`SITS_REPORT_DIR`
    를 넣자마자 `test_scan_is_not_vacuous` 가 그 사실을 잡았다.
    """
    found: dict[tuple[str, str], str] = {}
    for root in _SCAN_ROOTS:
        for path in (_REPO / root).rglob("*.py"):
            if _SKIP_PARTS & set(path.parts):
                continue
            src = path.read_text(encoding="utf-8", errors="replace")
            if '"reports"' not in src and "'reports'" not in src:
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in tree.body:            # 모듈 최상위만
                if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.BinOp):
                    continue
                # `A / "reports" / "sub"` → 우변이 "sub", 그 좌변 안에 "reports" 가 있어야 한다.
                if not isinstance(node.value.op, ast.Div) or not isinstance(node.value.right, ast.Constant):
                    continue
                sub = node.value.right.value
                if not isinstance(sub, str):
                    continue
                left = node.value.left
                if not (isinstance(left, ast.BinOp) and isinstance(left.right, ast.Constant)
                        and left.right.value == "reports"):
                    continue
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if not names:
                    continue
                mod = str(path.relative_to(_REPO).with_suffix("")).replace("\\", ".").replace("/", ".")
                found[(mod, names[0])] = sub
    return found


class TestTheIsolationTableIsComplete:
    def test_scan_is_not_vacuous(self):
        """스캔이 아무것도 못 찾으면 아래 대조는 **전부 통과한다** — 그건 가드가 아니다."""
        found = _module_level_report_dirs()
        assert len(found) >= len(_REPORT_DIR_TARGETS), (
            f"`reports/<sub>` 모듈 상수를 {len(found)}개밖에 못 찾았다 — 스캔이 깨졌다"
        )

    def test_every_report_dir_constant_is_isolated(self):
        """코드가 가진 `reports/<sub>` 상수 전수 == `conftest._REPORT_DIR_TARGETS`.

        새 산출 디렉터리를 만들고 표에 안 넣으면 **여기서 실패한다**. 그때 할 일은 이 테스트를
        고치는 게 아니라 `_REPORT_DIR_TARGETS` 에 한 줄을 더하는 것이다.
        """
        found = _module_level_report_dirs()
        declared = {(mod, attr): sub for mod, attr, sub in _REPORT_DIR_TARGETS}
        missing = {k: v for k, v in found.items() if k not in declared}
        assert not missing, (
            "격리 표에 없는 `reports/` 산출 디렉터리가 있다 — 테스트가 사용자 트리에 쓴다:\n  "
            + "\n  ".join(f"{m}.{a} → reports/{s}" for (m, a), s in missing.items())
            + "\n→ tests/conftest.py 의 `_REPORT_DIR_TARGETS` 에 추가할 것"
        )

    def test_declared_targets_still_exist(self):
        """표가 가리키는 상수가 사라졌으면(이름 변경·삭제) 격리는 **조용히 아무것도 안 한다**."""
        stale = []
        for mod_path, attr, sub in _REPORT_DIR_TARGETS:
            try:
                mod = __import__(mod_path, fromlist=["_"])
            except ImportError as exc:      # 의존성 부재 환경은 그 모듈의 쓰기 경로 자체가 없다
                pytest.skip(f"{mod_path} 임포트 불가({exc}) — 이 환경에서는 대조할 수 없다")
            if not hasattr(mod, attr):
                stale.append(f"{mod_path}.{attr}")
        assert not stale, f"격리 표가 없는 상수를 가리킨다: {stale}"


class TestIsolationActuallyRedirects:
    """표에 있는 것이 **실제로** 임시 경로를 가리키는가 — 선언과 효과는 다른 축이다."""

    def test_targets_point_outside_user_reports(self):
        user_reports = (_REPO / "reports").resolve()
        leaking = []
        for mod_path, attr, _sub in _REPORT_DIR_TARGETS:
            try:
                mod = __import__(mod_path, fromlist=["_"])
            except ImportError:
                continue
            cur = pathlib.Path(str(getattr(mod, attr))).resolve()
            if cur == user_reports or user_reports in cur.parents:
                leaking.append(f"{mod_path}.{attr} → {cur}")
        assert not leaking, (
            "세션 격리가 걸렸는데도 사용자 `reports/` 를 가리킨다 — 픽스처가 안 돌았거나 "
            "다른 코드가 되돌렸다:\n  " + "\n  ".join(leaking)
        )

    def test_writing_through_the_constant_stays_in_tmp(self):
        """상수를 거쳐 실제로 쓰면 임시 트리에 떨어진다 — 경로만 보고 끝내지 않는다."""
        from workflow import impact_changes
        target = impact_changes.ensure_change_dir()
        probe = target / ".r38_isolation_probe"
        probe.write_text("probe", encoding="utf-8")
        try:
            assert probe.exists()
            assert (_REPO / "reports").resolve() not in probe.resolve().parents
        finally:
            probe.unlink(missing_ok=True)


class TestThePathIsNotDuplicated:
    """같은 산출 경로를 두 모듈이 각자 조립하면, 한 곳을 격리해도 나머지가 샌다. (R38 D-1)

    실제로 `reports/impact_audit` 이 **세 곳**에서 조립되고 있었다 — `impact_audit.AUDIT_DIR`,
    `scm_fallback.AUDIT_DIR`(복제 상수), `impact_orchestrator` 안의 인라인 리터럴. 앞의 둘만
    격리해도 세 번째가 사용자 트리에 계속 썼고, 그렇게 쌓인 `*_review_required_*.md` 가
    `build_timeline` 의 `cumulative_flag_docs`(ISO 26262 검토 대기 배너)를 463건까지 부풀렸다.
    """

    def test_no_two_modules_claim_the_same_report_subdir(self):
        found = _module_level_report_dirs()
        by_sub: dict[str, list[str]] = {}
        for (mod, attr), sub in found.items():
            by_sub.setdefault(sub, []).append(f"{mod}.{attr}")
        dup = {s: ms for s, ms in by_sub.items() if len(ms) > 1}
        assert not dup, (
            "같은 `reports/` 하위를 두 모듈이 각자 정의한다 — 하나를 격리해도 나머지가 샌다:\n  "
            + "\n  ".join(f"reports/{s}: {', '.join(ms)}" for s, ms in dup.items())
        )

    def test_isolated_subdirs_are_never_reassembled_anywhere(self):
        """격리 대상 하위 디렉터리는 **어디서 조립하든** 복제다 — 함수 안도 포함한다.

        ⚠ (R38) 이 검사는 **뮤테이션이 찾아낸 구멍**이다. 처음 판은 모듈 최상위 할당만 봐서,
        `scm_fallback._audit_dir()` 이 함수 안에서 `REPO_ROOT / "reports" / "impact_audit"` 를
        되살리는 뮤턴트가 **살아남았다**(M3). 실제로 `impact_orchestrator` 가 정확히 그 형태로
        새고 있었으므로, 가드가 못 보는 자리가 곧 결함이 사는 자리였다.

        표에 선언된 **단일 출처 모듈의 모듈 최상위 할당** 하나만 허용한다.
        """
        owners = {sub: mod for mod, _attr, sub in _REPORT_DIR_TARGETS}
        offenders: list[str] = []
        for path, _src, tree in _iter_scanned_files():
            mod = str(path.relative_to(_REPO).with_suffix("")).replace("\\", ".").replace("/", ".")
            if mod in _INLINE_EXCEPTIONS:
                continue
            toplevel_nodes = {id(n.value) for n in tree.body if isinstance(n, ast.Assign)}
            for node in ast.walk(tree):
                sub = _report_subdir_of(node)
                if sub is None or sub not in owners:
                    continue
                if owners[sub] == mod and id(node) in toplevel_nodes:
                    continue          # 단일 출처 그 자신 — 유일하게 허용되는 자리
                offenders.append(f"{mod}:{getattr(node, 'lineno', '?')} → reports/{sub} "
                                 f"(출처는 {owners[sub]})")
        assert not offenders, (
            "격리 대상 경로를 단일 출처 밖에서 다시 조립한다 — 그 자리는 격리를 비켜간다:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_exception_list_is_not_a_dumping_ground(self):
        """예외에는 **사유**가 있어야 하고, 그 모듈이 실제로 존재해야 한다.

        사유 없는 예외는 곧 잊히고, 잊힌 예외는 격리가 있다고 믿게 만든다(이 저장소의
        `_DEFERRED` 면제가 사유 만료 뒤에도 살아 있던 전례와 같은 계열).
        """
        assert _INLINE_EXCEPTIONS, "예외가 0개면 위 검사에서 제외 분기를 지울 것"
        for mod, why in _INLINE_EXCEPTIONS.items():
            assert why and len(why) > 5, f"{mod}: 예외 사유가 비어 있다"
            path = _REPO / (mod.replace(".", "/") + ".py")
            assert path.exists(), f"{mod}: 예외가 없는 모듈을 가리킨다 — 목록에서 지울 것"

    def test_audit_dir_has_no_inline_literal_left(self):
        """`impact_orchestrator` 가 감사 경로를 **다시 조립하지 않는다**(단일 출처를 호출한다).

        ⚠ 문자열 검색으로 하면 **주석과 docstring 이 걸린다**(이 규칙을 설명하는 문장 자체가
        그 리터럴을 담는다 — 처음 판이 실제로 그렇게 실패했다). AST 로 *조립식*만 본다.
        """
        src = (_REPO / "workflow" / "impact_orchestrator.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        inline = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant) and node.right.value == "impact_audit"
            and isinstance(node.left, ast.BinOp) and isinstance(node.left.right, ast.Constant)
            and node.left.right.value == "reports"
        ]
        assert not inline, (
            f"감사 디렉터리를 인라인으로 다시 조립한다(line {inline}) — "
            "`impact_audit.ensure_audit_dir()` 를 쓸 것"
        )


class TestUserDataFilesAreIsolated:
    """사용자 **파일**(설정·채팅 DB)도 격리된다 — 디렉터리만으로는 부족하다. (R41 N11·N12)

    R38 은 `reports/` **디렉터리**를 막았다. 그런데 테스트가 건드릴 수 있는 사용자 데이터는
    디렉터리만이 아니다:
      - `config/file_mode.json` — 파일 모드는 **영속**이라(`영속 > env > local`) 한 번 바뀌면
        다음 기동까지 남는다.
      - `config/cloudium_extra_prefixes.json` — `test_admin_gate` 가 admin 자격으로
        `add-allowed-prefix` 를 **실제로 호출**한다. 지금 안 터지는 이유는 격리가 아니라
        resolver 가 local 이라 400 에서 반환하기 때문이었다("지금 안 터진다" 는 격리가 아니다).
      - `reports/chat_history.sqlite` — 앞판은 전역 싱글톤이 tmp 로 박히는 데 기댔다(순서 취약).
    """

    def test_config_files_point_outside_the_repo_config_dir(self):
        from tests.conftest import _CONFIG_FILE_TARGETS

        user_config = (_REPO / "config").resolve()
        leaking = []
        for mod_path, attr, _fname in _CONFIG_FILE_TARGETS:
            try:
                mod = __import__(mod_path, fromlist=["_"])
            except ImportError:
                continue
            cur = pathlib.Path(str(getattr(mod, attr))).resolve()
            if cur.parent == user_config:
                leaking.append(f"{mod_path}.{attr} → {cur}")
        assert not leaking, (
            "세션 격리가 걸렸는데도 사용자 `config/` 를 가리킨다:\n  " + "\n  ".join(leaking)
        )

    def test_config_table_is_not_empty(self):
        """표가 비면 위 검사가 **전부 통과한다** — 그건 가드가 아니다."""
        from tests.conftest import _CONFIG_FILE_TARGETS

        assert len(_CONFIG_FILE_TARGETS) >= 2

    def test_chat_history_db_is_isolated(self):
        """채팅 DB 기본 경로가 사용자 `reports/` 밖을 가리킨다."""
        from backend.services import chat_history_db as chat

        cur = pathlib.Path(str(chat._default_db_path())).resolve()
        assert (_REPO / "reports").resolve() not in cur.parents, (
            f"채팅 DB 기본 경로가 사용자 트리를 가리킨다: {cur}"
        )

    def test_chat_engine_cache_is_per_path(self):
        """경로별 캐시여야 `db_path` 인자가 유효하다 — 단일 싱글톤이면 첫 경로가 전부를 먹는다.

        (R41 N11) `workflow/quality/db.py` 가 같은 결함을 먼저 고쳤고, 그 주석이 이유를 적어 뒀다:
        *"단일 `_engine` 싱글톤이라 첫 init 후 db_path 인자가 무시돼 테스트 격리가 깨졌다"*.
        """
        from backend.services import chat_history_db as chat

        assert hasattr(chat, "_engines"), "경로별 엔진 캐시가 없다(전역 싱글톤으로 되돌아갔다)"
        assert isinstance(chat._engines, dict)
        assert not hasattr(chat, "_engine"), "전역 단일 엔진이 되살아났다"
