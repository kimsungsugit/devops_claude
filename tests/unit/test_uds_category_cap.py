"""UDS 분류별 상한(`max_items`)이 자를 때 **무엇을 잘랐는지 남기는가**.

## 왜 필요한가

`generate_uds_source_sections` 는 인터페이스·내부·매크로·타입 등 **11개 축을 전부**
`[:max_items]` 로 자른다. 그런데 오래 아무 기록도 남기지 않았다 — 같은 함수의 전역
축(`globals_scan` = `_globals_loss`)은 "기록이 없으면 '이 프로젝트엔 원래 없다' 로
오독한다" 는 이유로 손실을 남기는데 카테고리 축만 빠져 있던 **비대칭**이다.

그 침묵이 준비 게이트까지 번졌다: 게이트는 `max_items_per_category` 상한을 공시하면서도
**"실제로 자르고 있는가" 는 말할 수 없었다.** 실측(KJPDS02_RD + PDS64_FBL): 소스의
`#define` 이 12,941개인데 분류 상한은 120 이다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from report_gen.uds_generator import generate_uds_source_sections


def _write_macros(root: Path, count: int) -> None:
    root.joinpath("macros.h").write_text(
        "\n".join(f"#define TEST_MACRO_{i} ({i})" for i in range(count)),
        encoding="utf-8",
    )


@pytest.mark.timeout(300)
def test_category_cap_truncation_is_recorded(tmp_path: Path, monkeypatch) -> None:
    """상한에 걸리면 축별로 `total / cap / dropped` 가 남아야 한다."""
    import config as _cfg

    monkeypatch.setattr(_cfg, "UDS_MAX_FUNCTION_ITEMS", 2, raising=False)
    _write_macros(tmp_path, 8)

    out = generate_uds_source_sections(str(tmp_path), preprocess=False)
    caps = out.get("category_caps")
    assert caps, "카테고리 절단 통계 자체가 없다"
    assert caps["measured"] is True
    assert caps["cap"] == 2
    assert caps["any_truncated"] is True, caps

    truncated = caps["truncated"]
    assert truncated, "상한을 2 로 낮췄는데 잘린 축이 하나도 없다"
    for name, d in truncated.items():
        # 셋이 서로 맞아야 한다 — `dropped` 만 있으면 분모를 몰라 심각도를 못 잰다.
        assert d["total"] > d["cap"], f"{name}: 상한 이하인데 절단으로 기록됐다"
        assert d["dropped"] == d["total"] - d["cap"], f"{name}: {d}"


@pytest.mark.timeout(300)
def test_no_truncation_is_not_reported_as_loss(tmp_path: Path, monkeypatch) -> None:
    """상한에 안 닿으면 **없는 손실을 만들지 않는다**.

    음성 대조군이 없으면 "무조건 절단으로 기록" 하는 뮤턴트가 위 테스트를 통과한다.
    """
    import config as _cfg

    monkeypatch.setattr(_cfg, "UDS_MAX_FUNCTION_ITEMS", 500, raising=False)
    _write_macros(tmp_path, 8)

    out = generate_uds_source_sections(str(tmp_path), preprocess=False)
    caps = out["category_caps"]
    assert caps["any_truncated"] is False, caps["truncated"]
    assert caps["truncated"] == {}


@pytest.mark.timeout(300)
def test_truncation_actually_shortens_the_output(tmp_path: Path, monkeypatch) -> None:
    """기록만 남기고 실제로는 안 자르는(또는 그 반대) 어긋남을 막는다.

    통계와 산출물이 갈리면 통계가 거짓 증거가 된다 — 이 저장소가 반복해서 밟은 결함이다.
    """
    import config as _cfg

    monkeypatch.setattr(_cfg, "UDS_MAX_FUNCTION_ITEMS", 3, raising=False)
    _write_macros(tmp_path, 20)

    out = generate_uds_source_sections(str(tmp_path), preprocess=False)
    truncated = out["category_caps"]["truncated"]
    for name, d in truncated.items():
        section = out.get(name)
        if not isinstance(section, list):
            continue
        assert len(section) == d["cap"], (
            f"{name}: 통계는 {d['cap']} 로 잘랐다는데 실제 산출은 {len(section)} 개다"
        )
