# -*- coding: utf-8 -*-
"""산출물 경로 충돌 — **전수 스윕 가드**(인계 P6 잔여).

## 무엇이 문제인가

산출물 경로는 전부 초 단위 타임스탬프로 만든다. 출력 디렉터리(`DEFAULT_REPORT_DIR`)에는
**사용자 구분이 없다** — 실측: `_resolve_base_dir` → `config.DEFAULT_REPORT_DIR`("reports")
로 전 사용자가 같은 트리를 쓴다. 그래서 같은 초에 같은 키의 두 요청은 **같은 경로**를
만들고, 나중 쓰기만 남는다. ISO 26262 산출물에서 이건 단순 덮어쓰기가 아니라
**A 가 받은 문서가 실은 B 의 것**이 되는 일이고, 어디에도 흔적이 안 남는다.

## 왜 개별 테스트가 아니라 스윕인가

인계 P6 은 "5곳 중 2곳만 방어됨"이라고 적혀 있었다. 그런데 이 결함은 **쌍둥이 형태로
번식**한다 — 실측(2026-08-19)에서 확인한 것만:

    local  SUTS vectorcast 패키지 = 선점 O   ↔  local  SITS 쌍둥이 = 선점 X
    jenkins UDS spec docx        = 선점 O   ↔  helpers UDS spec 쌍둥이 = 선점 X
    jenkins 리포트 zip·Excel      = 선점 O   ↔  jenkins 콜트리 저장    = 선점 X

한쪽만 고치면 다음 라운드에 다른 쪽이 다시 올라온다. 그래서 개별 단언이 아니라
**"미선점 사이트가 0 이어야 한다"**를 고정한다. 새 사이트가 생기면 이 테스트가 깨지고,
그때 선점하거나 `# path-collision-ok: <사유>` 로 판단을 남기게 된다.

⚠ 스캐너가 아무것도 못 찾는 상태(루트 오타·문법 오류로 전부 skip)로 조용히 통과할 수
  있으므로, **심어 둔 결함을 잡는지**도 함께 단언한다.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List

import pytest

from tests.unit._path_collision_scan import ROOTS, scan_text, scan_unreserved

# --------------------------------------------------------------------------- #
# 1. 전수 스윕
# --------------------------------------------------------------------------- #


def test_no_unreserved_ts_output_paths():
    hits = scan_unreserved()
    if hits:
        detail = "\n".join(f"  {f}:{ln}  {expr}" for f, ln, expr in hits)
        pytest.fail(
            "ts 기반 산출물 경로가 선점되지 않았다 — 같은 초의 두 요청이 서로를 덮는다.\n"
            f"{detail}\n"
            "→ `reserve_unique_path`/`reserve_unique_dir` 로 감싸거나, 의도적이면 바로 위에\n"
            "   `# path-collision-ok: <사유>` 를 달 것(사유 없는 면제는 인정하지 않는다).")


def test_the_sweep_actually_looks_at_something():
    """⚠ 루트가 어긋나 0 파일을 훑고 '이상 없음'이 되는 걸 막는다."""
    present = [r for r in ROOTS if Path(r).is_dir()]
    assert present == list(ROOTS), f"스캔 루트가 사라졌다: {set(ROOTS) - set(present)}"


# --------------------------------------------------------------------------- #
# 2. 스캐너 자체 검증 — 심은 결함을 잡는가, 정상을 오검출하지 않는가
# --------------------------------------------------------------------------- #

_DEFECT = '''
from datetime import datetime
def f(out_dir):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"report_{ts}.xlsx"
    return out_path
'''

_RESERVED = '''
from datetime import datetime
def f(out_dir):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = reserve_unique_path(out_dir / f"report_{ts}.xlsx")
    return out_path
'''

_RESERVED_LATER = '''
from datetime import datetime
def f(out_dir):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    want = out_dir / f"report_{ts}.xlsx"
    out_path = reserve_unique_path(want)
    return out_path
'''

_EXEMPTED = '''
from datetime import datetime
def f(out_dir):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # path-collision-ok: 여러 줄짜리
    #   사유 블록이다.
    out_path = out_dir / f"report_{ts}.xlsx"
    return out_path
'''

_INDIRECT = '''
from datetime import datetime
def f(out_dir):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"local_report_{ts}"
    out_path = out_dir / f"{base}.docx"
    return out_path
'''

_MESSAGE_ONLY = '''
from datetime import datetime
def f(log):
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log.append(f"Run {run_id} | done")
'''

_DIVISION = '''
from datetime import datetime
def f(covered, total):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rate = covered / total
    return ts, rate
'''

_OTHER_SCOPE = '''
from datetime import datetime
def writer(out_dir):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"x_{ts}.xlsx"
    return reserve_unique_path(out_dir / filename)

def reader(in_dir, filename):
    return in_dir / filename
'''


class TestTheScannerItself:
    def test_planted_defect_is_found(self):
        assert scan_text(_DEFECT), "심어 둔 미선점 경로를 못 잡았다 — 스캐너가 죽어 있다"

    def test_reserved_is_clean(self):
        assert scan_text(_RESERVED) == []

    def test_reserved_on_a_later_line_is_clean(self):
        """`want = …` 로 조립하고 두 줄 뒤에 선점하는 형태(실제 코드에 있다)."""
        assert scan_text(_RESERVED_LATER) == []

    def test_documented_exemption_is_clean(self):
        assert scan_text(_EXEMPTED) == []

    def test_indirect_fstring_is_found(self):
        """`base = f"…{ts}"` → `dir / f"{base}.docx"` 도 잡아야 한다."""
        assert scan_text(_INDIRECT), "간접 f-string 경유를 놓쳤다"

    def test_message_string_is_not_a_path(self):
        """⚠ `f"Run {ts} | …"` 는 경로가 아니다 — 오검출하면 아무도 안 고친다."""
        assert scan_text(_MESSAGE_ONLY) == []

    def test_division_is_not_a_path(self):
        """⚠ 오염을 넓게 잡았을 때 `covered / total` 이 통째로 잡혔다(오탐 20건+)."""
        assert scan_text(_DIVISION) == []

    def test_taint_does_not_leak_across_functions(self):
        """⚠ 모듈 스코프가 함수 지역명을 보면 요청 파라미터 `filename` 이 오염된다."""
        assert scan_text(_OTHER_SCOPE) == [], "다른 함수의 이름이 새어 들어왔다"


# --------------------------------------------------------------------------- #
# 3. 동작 — 감사 레코드는 원자적으로 유일해야 한다
# --------------------------------------------------------------------------- #


class _FrozenClock:
    """같은 초를 강제한다 — 충돌은 '드물게' 가 아니라 '항상' 재현돼야 검사가 된다."""

    @staticmethod
    def now():
        return _dt.datetime(2026, 8, 19, 12, 0, 0)


class TestImpactAuditIsAtomicallyUnique:
    """ISO 26262 감사 레코드 — "무엇을 왜 분석/제외했는지"의 유일한 durable 기록.

    ⚠ 예전엔 `while out.exists(): …` 로 비켜갔다. 그건 TOCTOU 라, 두 실행이 같은 순간에
      '없음'을 보면 둘 다 같은 이름을 고른다. 여기서의 손실 = 추적성 손실이다.
    """

    @pytest.fixture(autouse=True)
    def _audit_dir(self, tmp_path, monkeypatch):
        from workflow import impact_audit as IA

        monkeypatch.setattr(IA, "AUDIT_DIR", tmp_path / "impact_audit")
        monkeypatch.setattr(IA, "datetime", _FrozenClock)
        self.IA = IA
        self.dir = tmp_path / "impact_audit"

    def _write(self, marker: str) -> Path:
        payload: Dict[str, Any] = {"scm_id": "kjpds02", "marker": marker}
        return self.IA.write_impact_audit(payload)

    def test_same_second_writes_do_not_overwrite(self):
        a = self._write("A")
        b = self._write("B")
        assert a != b, "같은 초의 두 감사 레코드가 한 경로를 썼다"
        import json
        assert json.loads(a.read_text(encoding="utf-8"))["marker"] == "A", "앞 기록이 덮였다"
        assert json.loads(b.read_text(encoding="utf-8"))["marker"] == "B"

    def test_reader_glob_still_matches(self):
        """⚠ 접미사 형식이 바뀌어도 읽기(`impact_*.json` glob)는 계속 맞아야 한다."""
        paths = [self._write(str(i)) for i in range(3)]
        found = sorted(p.name for p in self.dir.glob("impact_*.json"))
        assert found == sorted(p.name for p in paths), (found, paths)

    def test_no_toctou_loop_remains(self):
        """구조 가드 — `while …exists()` 로 되돌아가면 원자성이 사라진다."""
        src = Path("workflow/impact_audit.py").read_text(encoding="utf-8")
        code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
        assert not any("while out.exists()" in ln for ln in code), (
            "TOCTOU 루프가 돌아왔다 — `reserve_unique_path` 로 원자 선점할 것")


# --------------------------------------------------------------------------- #
# 4. 동작 — 쌍둥이 대칭
# --------------------------------------------------------------------------- #


class TestTwinSitesStayedSymmetric:
    """한쪽만 고쳐지는 게 이 결함의 재생산 경로다 — 쌍을 함께 고정한다."""

    @pytest.mark.parametrize("path,needles", [
        ("backend/routers/local.py", ["suts_vectorcast_", "sits_vectorcast_"]),
        ("backend/routers/qac.py", ["qac_report_", "qac_impact_"]),
    ])
    def test_both_twins_reserve(self, path, needles):
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        for needle in needles:
            hits = [i for i, ln in enumerate(lines)
                    if needle in ln and not ln.lstrip().startswith("#")]
            assert hits, f"{path}: {needle!r} 를 못 찾았다 — 앵커가 깨졌다"
            window: List[str] = []
            for i in hits:
                window += lines[max(0, i - 3):i + 3]
            assert any("reserve_unique_" in ln for ln in window), (
                f"{path}: {needle!r} 쪽이 선점되지 않았다(쌍둥이 비대칭)")
