"""원문 읽기 상한이 **레지스터 정의를 통째로 지우던** 경로.

## 무엇이 문제였나 (KJPDS02_PV 실측, 2026-08-12)

`_read_text_limited` 의 기본 상한이 200,000 바이트였다. 그런데 이 프로젝트의 레지스터
맵은 그보다 훨씬 크다:

    Generated_Code/IO_Map.h              680,639 B  → 29.4% 만 읽음
    Project_Headers/mc9s12zvl64.h        670,149 B
    Sources/LIN/lin16_cfg/lin_cfg.h      256,019 B
    (소스 트리 전체 4.0MB 중 **1.0MB(24.1%)** 가 버려지고 있었다)

잘린 뒤쪽에 무엇이 있었나 — IO_Map.h 한 파일 기준:

    매크로 정의        5,622 중 **3,881 소실 (69.0%)**
    extern 전역 후보     363 중 **251 소실 (69.1%)**

레지스터 정의는 파일 뒤쪽에 몰려 있어서, 앞쪽 `_PTT`·`_FCLKDIV` 는 살아남고 뒤쪽
`_ADC0CTL`·`_SCI0CR2`·`_CPMUINT`·`_ECCIE`·`_LP0IF`·`_TIM0TCNT` 는 통째로 없었다.
그래서 "SFR 을 부분적으로만 인식한다"는 파서 결함처럼 보였지만, **파서는 멀쩡했고
파일을 끝까지 읽지 않았을 뿐**이다.

## 왜 조용했나

세 가지가 겹쳤다.

1. 캡이 아무 기록도 남기지 않았다 — "이 프로젝트엔 그 매크로가 원래 없다" 와
   구분할 방법이 없었다.
2. tree-sitter 경로(`c_parser.parse_c_project`)는 같은 파일을 **캡 없이**
   `read_bytes()` 로 읽는다. 그래서 전역 **선언**은 잡히는데 그 전역을 가리키는
   **매크로**만 사라져, 매크로 접기(`macro_globals_map`)가 반쪽만 동작했다.
   두 경로의 비대칭이라 어느 쪽 로그를 봐도 이상이 없었다.
3. 캡은 방어도 아니었다 — `_read_bytes_resolver_aware` 가 파일 전체를 이미 메모리로
   읽은 **뒤** 잘라내므로 I/O 도 피크 메모리도 아끼지 못한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from report_gen.source_parser import (
    _SRC_READ_MAX_BYTES,
    _extract_c_macro_defs,
    _read_source_text,
    _read_text_limited,
)


class TestReadCap:
    def test_cap_covers_a_real_register_map(self):
        """⚠ 실물 IO_Map.h 가 680,639 B 다. 상한이 그보다 작으면 다시 잘린다."""
        assert _SRC_READ_MAX_BYTES >= 700_000, (
            "이 저장소가 실제로 파싱하는 레지스터 맵(680KB)보다 작은 상한은 "
            "SFR 을 다시 침묵 삭제한다"
        )

    def test_a_file_larger_than_the_old_cap_is_read_whole(self, tmp_path):
        """옛 기본값 200,000 을 넘는 파일이 **끝까지** 읽혀야 한다."""
        f = tmp_path / "IO_Map.h"
        pad = "\n".join(f"#define PAD_{i:06d} {i}" for i in range(12_000))
        f.write_text(pad + "\n#define TAIL_MARKER 1\n", encoding="utf-8")
        assert f.stat().st_size > 200_000, "테스트 전제가 깨졌다 — 옛 캡을 넘지 않는다"
        text, raw_len, truncated = _read_source_text(f)
        assert truncated is False
        assert raw_len == f.stat().st_size
        assert "TAIL_MARKER" in text, "뒤쪽 정의가 사라지면 레지스터가 통째로 없어진다"

    def test_macro_defs_at_the_tail_survive(self, tmp_path):
        """캡 뒤쪽의 `#define`(= 실제 레지스터가 있는 자리)이 살아 있는지."""
        f = tmp_path / "IO_Map.h"
        pad = "\n".join(f"#define PAD_{i:06d} {i}" for i in range(12_000))
        f.write_text(
            pad + "\nextern volatile ADC0STSSTR _ADC0STS @0x00000602;\n"
            "#define ADC0STS        _ADC0STS.Byte\n"
            "#define ADC0STS_READY  _ADC0STS.Bits.READY\n",
            encoding="utf-8",
        )
        defs = dict(_extract_c_macro_defs(_read_text_limited(f)))
        assert defs.get("ADC0STS") == "_ADC0STS.Byte"
        assert defs.get("ADC0STS_READY") == "_ADC0STS.Bits.READY"

    def test_the_cap_still_exists_and_is_reported(self, tmp_path):
        """상한 자체는 남는다(병적으로 큰 생성 파일 방어). 대신 **닿으면 말한다**.

        옛 판은 잘라놓고 아무 말도 하지 않아 손실이 보이지 않았다.
        """
        f = tmp_path / "big.h"
        f.write_text("A" * 5_000, encoding="utf-8")
        text, raw_len, truncated = _read_source_text(f, max_bytes=1_000)
        assert truncated is True
        assert raw_len == 5_000
        assert len(text) == 1_000

    def test_missing_file_is_not_reported_as_truncated(self, tmp_path):
        """읽기 실패를 "잘렸다" 로 세면 없는 손실을 보고한다."""
        text, raw_len, truncated = _read_source_text(tmp_path / "nope.h")
        assert (text, raw_len, truncated) == ("", 0, False)

    @pytest.mark.parametrize("cap", [0, None])
    def test_falsy_cap_means_no_limit(self, tmp_path, cap):
        f = tmp_path / "x.h"
        f.write_text("B" * 3_000, encoding="utf-8")
        text, _raw, truncated = _read_source_text(f, max_bytes=cap)
        assert truncated is False and len(text) == 3_000

    def test_limited_wrapper_still_returns_text_only(self, tmp_path):
        """`_read_text_limited` 는 기존 계약(문자열 하나)을 유지해야 한다 —
        호출부가 report_gen 안팎에 흩어져 있다."""
        f = tmp_path / "x.c"
        f.write_text("void f(void){}\n", encoding="utf-8")
        assert isinstance(_read_text_limited(Path(f)), str)
