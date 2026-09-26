"""(R46 실사고 2026-09-09) UDS 생성기가 콤마 결합 다중 소스 루트를 통째로 `exists()` 에 물어
소스 분석을 조용히 건너뛰었다 — kjpds02_pv 라이브 생성이 함수 0개짜리 60MB 문서를 'success' 로 냈다.

가드 두 층: ① 헬퍼가 결합 문자열을 루트별로 가르는가 ② `_uds_generate_from_paths` 본문이 그 헬퍼로
분기하는가(헬퍼만 멀쩡하고 아무도 안 부르면 초록 — R44 의 배선 누락 교훈)."""
from __future__ import annotations

from tests.unit._source_probe import source_of


def test_helper_splits_joined_roots_into_existing_and_missing(tmp_path):
    from backend.helpers.uds import _existing_source_roots

    a = tmp_path / "APP"
    a.mkdir()
    b = tmp_path / "BOOT"
    b.mkdir()
    ghost = tmp_path / "GONE"
    joined = f"{a},{ghost};{b}"
    existing, missing = _existing_source_roots(joined)
    assert existing == [str(a), str(b)]
    assert missing == [str(ghost)]
    # 결합 문자열 통째로는 존재하지 않는다 — 옛 판정이 False 였던 이유 그 자체
    from pathlib import Path
    assert not Path(joined).exists()
    assert _existing_source_roots("") == ([], []) and _existing_source_roots(None) == ([], [])


def test_generate_from_paths_is_wired_to_the_helper():
    from backend.helpers import uds

    src = source_of(uds._uds_generate_from_paths)
    assert "_source_roots_for_generation(source_root)" in src
    # 옛 형태(결합 문자열 통째 exists) 복귀 금지
    assert "Path(source_root).resolve() if source_root else None" not in src


def test_generate_from_paths_has_no_undefined_names():
    """(R46) 첫 패치가 `source_root_path` 정의를 지우고 뒤의 참조 3곳을 남겨 라이브에서
    `NameError` 로 죽었다 — ratchet 은 **바뀐 줄만** 보므로 지워진 정의가 만드는 미정의 이름을
    못 본다. 함수 본문 전체를 pyflakes 급으로 잰다(ruff F821)."""
    import subprocess
    import sys

    from backend.helpers import uds

    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F821,F823", "--output-format", "concise", uds.__file__],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-500:]


def test_generation_root_string_treats_single_and_multi_root_the_same(tmp_path):
    """(R46 리뷰 W3/M1b) 배선 가드가 구조뿐이라 `if _src_roots:` → `if len(_src_roots) > 1:`
    (단일 루트 프로젝트가 소스 분석을 통째로 건너뜀 = 원래 대참사) 뮤턴트가 살아남았다.
    생성기에 넘어가는 **문자열 자체**를 단언한다 — 단일 루트도, 다중 루트도, 첫 루트가 빠져도."""
    from backend.helpers.uds import _source_roots_for_generation

    a = tmp_path / "APP"
    a.mkdir()
    b = tmp_path / "BOOT"
    b.mkdir()
    gone = tmp_path / "GONE"
    assert _source_roots_for_generation(str(a)) == (str(a), [])
    assert _source_roots_for_generation(f"{a},{b}") == (f"{a},{b}", [])
    assert _source_roots_for_generation(f"{gone},{b}") == (str(b), [str(gone)])
    assert _source_roots_for_generation(str(gone)) == ("", [str(gone)])
    assert _source_roots_for_generation("") == ("", [])


def test_sibling_generation_sites_do_not_pass_only_the_first_root():
    """(R46 리뷰 C1) 고친 건 async jenkins UDS 한 곳뿐이었고 형제 5곳(동기 jenkins UDS ·
    local UDS · STS/SUTS/SITS 함수 상세)은 첫 루트만 넘겨 **같은 프로젝트의 함수 집합이
    누른 버튼에 따라 달라졌다**. 두 라우터에서 첫 루트 Path 를 생성기/캐시에 직접 넘기는
    호출이 0 이어야 한다."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    bad = []
    for rel in ("backend/routers/jenkins.py", "backend/routers/local.py"):
        text = (root / rel).read_text(encoding="utf-8")
        for m in re.finditer(r"generate_uds_source_sections\(\s*str\(source_root_path\)", text):
            bad.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1} generate(str(source_root_path))")
        for m in re.finditer(r"_get_source_sections_cached\(str\(source_root_path\)\)", text):
            bad.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1} cached(str(source_root_path))")
    assert not bad, bad
    # 배선이 실제로 있는지도 — 0 건이면 이 가드는 공허하다
    j = (root / "backend/routers/jenkins.py").read_text(encoding="utf-8")
    loc = (root / "backend/routers/local.py").read_text(encoding="utf-8")
    assert j.count("_source_roots_for_generation") >= 2
    assert loc.count("_all_source_roots_str(source_root)") >= 3 and "_source_roots_for_generation" in loc
