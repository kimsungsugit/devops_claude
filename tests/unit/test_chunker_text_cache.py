"""대용량 문서 텍스트 추출 캐시 (계획서 §6 후보 12).

실측(2026-08-03): UDS 생성 한 번이 **같은 38.8MB 참조 SUDS 를 세 경로에서 각각** 읽는다.
`_read_text_from_file` 단독으로 **11.7초**(캐시 후 0.000초)이고, 여기에 `docx_builder`
함수정보 파싱 7.4초, `helpers/uds.py` SwCom diff 읽기가 더해져 계획서가 기록한
"생성 31.9초 중 24.3초" 가 설명된다. 서로를 모르는 세 호출처라 아무도 중복을 못 본다.

이 캐시가 안전한 이유는 반환값이 **불변 문자열**이라서다 — 이 저장소가 겪은 캐시 사고는
전부 공유 **가변** 구조를 호출자가 제자리 변경한 경우였다. 대신 무효화가 생명이라,
파일 신원 `(정규화 경로, mtime_ns, size)` 이 바뀌면 반드시 다시 읽어야 한다.
"""
import os
import tempfile
from pathlib import Path

import pytest

from workflow.rag import chunker


@pytest.fixture(autouse=True)
def _clean_cache():
    chunker._TEXT_CACHE.clear()
    yield
    chunker._TEXT_CACHE.clear()


@pytest.fixture
def big(tmp_path, monkeypatch):
    """캐시 자격을 얻는 파일을 만든다(임계값을 낮춰 테스트를 가볍게)."""
    monkeypatch.setattr(chunker, "_TEXT_CACHE_MIN_BYTES", 100)

    def _make(name="doc.txt", body="A" * 500):
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        return p

    return _make


class TestCacheHits:
    def test_second_read_is_served_from_cache(self, big):
        p = big()
        first = chunker._read_text_from_file(p)
        second = chunker._read_text_from_file(p)

        assert first == second
        assert first is second, "같은 객체가 아니면 다시 읽었다는 뜻이다"

    def test_cache_does_not_leak_between_files(self, big):
        a = big("a.txt", "AAAA" * 100)
        b = big("b.txt", "BBBB" * 100)

        assert chunker._read_text_from_file(a) != chunker._read_text_from_file(b)


class TestInvalidation:
    def test_content_change_is_picked_up(self, big):
        """stale 을 돌려주면 산출물이 조용히 옛 문서 기준이 된다."""
        p = big(body="OLD" * 100)
        assert "OLD" in chunker._read_text_from_file(p)

        p.write_text("NEW" * 100, encoding="utf-8")
        got = chunker._read_text_from_file(p)

        assert "NEW" in got and "OLD" not in got

    def test_same_size_different_content_is_picked_up(self, big):
        """크기만 보면 놓친다 — mtime_ns 가 키에 있어야 한다."""
        p = big(body="X" * 300)
        chunker._read_text_from_file(p)

        os.utime(p, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        p.write_text("Y" * 300, encoding="utf-8")
        got = chunker._read_text_from_file(p)

        assert set(got) == {"Y"}


class TestCacheEligibility:
    def test_small_files_are_not_cached(self, tmp_path):
        """작은 파일이 큰 항목을 밀어내면 캐시가 제 일을 못 한다."""
        p = tmp_path / "tiny.txt"
        p.write_text("hi", encoding="utf-8")

        chunker._read_text_from_file(p)

        assert len(chunker._TEXT_CACHE) == 0

    def test_missing_file_does_not_crash_or_cache(self, tmp_path):
        p = tmp_path / "nope.txt"
        assert chunker._text_cache_key(p) is None

    def test_temp_root_files_are_not_cached(self, monkeypatch):
        """`NamedTemporaryFile` 경로는 OS 가 재사용한다 — 남의 내용을 돌려줄 수 있다."""
        monkeypatch.setattr(chunker, "_TEXT_CACHE_MIN_BYTES", 10)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("Z" * 200)
            tmp_name = fh.name
        try:
            assert chunker._text_cache_key(Path(tmp_name)) is None
        finally:
            os.unlink(tmp_name)

    def test_subdirectories_of_temp_are_still_cacheable(self, big):
        """가드를 넓게 잡으면(temp 하위 전부) 캐시가 사실상 꺼진다 — pytest tmp_path 가 거기다."""
        p = big()
        assert chunker._text_cache_key(p) is not None


class TestCacheBound:
    def test_lru_evicts_oldest(self, big, monkeypatch):
        monkeypatch.setattr(chunker, "_TEXT_CACHE_MAX", 2)
        paths = [big(f"f{i}.txt", f"{i}" * 200) for i in range(3)]
        for p in paths:
            chunker._read_text_from_file(p)

        assert len(chunker._TEXT_CACHE) == 2
        # 가장 오래된 것이 밀려나고, 다시 읽으면 새 객체가 온다
        again = chunker._read_text_from_file(paths[0])
        assert again == "0" * 200


class TestUncachedPathStillWorks:
    def test_uncached_reader_is_the_real_implementation(self, big):
        """래퍼가 원본을 대체하지 않았는지 — 확장자별 분기가 그대로 살아 있어야 한다."""
        p = big("x.json", '{"k": 1}')
        assert chunker._read_text_uncached(p) == '{"k": 1}'

    def test_wrapper_delegates(self):
        from tests.unit._source_probe import source_of

        src = source_of(chunker._read_text_from_file)
        assert "_read_text_uncached" in src, "캐시 미스 시 실제 추출을 안 한다"
