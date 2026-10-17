"""array_collapse 단위 테스트 (DC-1) — C# ArrayCollapse.cs 시맨틱 고정.

핵심 보장: 다차원 full-box 배열만 접고, 그 외(스칼라/단일차원/부분채움)는 원본 순서 그대로
통과(no-op) → 일반 산출물 컬럼 구성 불변.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.array_collapse import (  # noqa: E402
    build,
    get_base_name,
    is_collapsed_column,
)


class TestGetBaseName:
    def test_scalar(self):
        assert get_base_name("counter") == ("counter", None)

    def test_single_dim(self):
        assert get_base_name("arr[3]") == ("arr", [3])

    def test_multi_dim(self):
        assert get_base_name("buffer[0][1][2]") == ("buffer", [0, 1, 2])

    def test_mid_index_not_trailing(self):
        # 끝이 인덱스가 아니면 base 그대로
        assert get_base_name("a[0].b") == ("a[0].b", None)

    def test_dotted_base(self):
        assert get_base_name("s.m[4][5]") == ("s.m", [4, 5])


class TestIsCollapsedColumn:
    def test_collapsed_header(self):
        assert is_collapsed_column("buffer[5*7*7]")

    def test_plain_index_not_collapsed(self):
        assert not is_collapsed_column("buffer[0][1]")
        assert not is_collapsed_column("scalar")


class TestBuildNoOp:
    """접기 대상 없으면 원본 순서 그대로 통과 (일반 케이스 불변 보장)."""

    def test_scalars_passthrough(self):
        names = ["a", "b", "c"]
        info = build(names)
        assert info.columns == names
        assert info.groups == {}

    def test_single_dim_not_collapsed(self):
        names = ["arr[0]", "arr[1]", "arr[2]"]
        info = build(names)
        assert info.columns == names  # 단일차원은 접지 않음
        assert info.groups == {}

    def test_partial_box_not_collapsed(self):
        # 2x2 경계상자인데 [1][1] 누락 → 부분채움 → 접지 않음
        names = ["m[0][0]", "m[0][1]", "m[1][0]"]
        info = build(names)
        assert info.columns == names
        assert info.groups == {}

    def test_empty(self):
        assert build([]).columns == []
        assert build(None).columns == []


class TestBuildCollapse:
    def test_2d_full_box(self):
        names = ["m[0][0]", "m[0][1]", "m[1][0]", "m[1][1]"]
        info = build(names)
        assert info.columns == ["m[2*2]"]
        assert info.is_collapsed("m[2*2]")
        grp = info.get_group("m[2*2]")
        assert grp is not None and grp.full_size() == 4

    def test_3d_full_box_buffer(self):
        # buffer[2][2][2] = 8 요소 모두 존재 → 단일 헤더
        names = [f"buffer[{i}][{j}][{k}]"
                 for i in range(2) for j in range(2) for k in range(2)]
        info = build(names)
        assert info.columns == ["buffer[2*2*2]"]

    def test_collapse_preserves_other_columns_order(self):
        names = ["pre", "m[0][0]", "m[0][1]", "m[1][0]", "m[1][1]", "post"]
        info = build(names)
        # 접힌 헤더는 첫 등장 위치(pre 다음)에 1개, pre/post 순서 보존
        assert info.columns == ["pre", "m[2*2]", "post"]


class TestFormatValues:
    def _grp(self):
        names = ["v[0][0]", "v[0][1]", "v[1][0]", "v[1][1]"]
        return build(names).get_group("v[2*2]")

    def test_uniform(self):
        grp = self._grp()
        out = grp.format_values(lambda k: "5")  # 전부 동일
        assert out == "5"

    def test_non_uniform_grouped_by_outer(self):
        grp = self._grp()
        vals = {"v[0][0]": "1", "v[0][1]": "2", "v[1][0]": "3", "v[1][1]": "4"}
        out = grp.format_values(lambda k: vals.get(k))
        assert out == "[0]: 1, 2\n[1]: 3, 4"

    def test_absent_members_skipped(self):
        grp = self._grp()
        # 일부만 존재 + 동일 → 단일 값
        out = grp.format_values(lambda k: "9" if k == "v[0][0]" else None)
        assert out == "9"

    def test_all_absent_empty(self):
        grp = self._grp()
        assert grp.format_values(lambda k: None) == ""


class TestFormatActual:
    def _grp(self):
        names = ["r[0][0]", "r[0][1]", "r[1][0]", "r[1][1]"]
        return build(names).get_group("r[2*2]")

    def test_all_pass_ok(self):
        grp = self._grp()
        text, all_pass = grp.format_actual(lambda k: True)
        assert text == "OK" and all_pass is True

    def test_some_fail_ng(self):
        grp = self._grp()
        fails = {"r[0][1]", "r[1][1]"}
        text, all_pass = grp.format_actual(lambda k: k not in fails)
        assert all_pass is False
        assert text.startswith("NG (2/4)")
        assert "[0][1]" in text and "[1][1]" in text

    def test_no_data_empty(self):
        grp = self._grp()
        text, all_pass = grp.format_actual(lambda k: None)
        assert text == "" and all_pass is True


class TestCollapseAll:
    """collapse_all=True — 단일차원·sparse 포함 모든 배열 접기 (2026-06-24 확장)."""

    def test_single_dim_collapses_only_in_collapse_all(self):
        names = ["a[0]", "a[1]", "a[2]"]
        # 기본 모드: 단일차원 미접기
        assert build(names).columns == names
        # collapse_all: 단일차원 접기 → "a[3]"(size=max+1)
        info = build(names, collapse_all=True)
        assert info.columns == ["a[3]"]
        assert info.is_collapsed("a[3]")

    def test_sparse_single_dim_collapses(self):
        # sparse(인덱스 0,5,19 — 갭) → full-box 아님이나 collapse_all이면 접힘
        names = ["buf[0]", "buf[5]", "buf[19]"]
        info = build(names, collapse_all=True)
        assert info.columns == ["buf[20]"]  # max+1=20
        grp = info.get_group("buf[20]")
        assert len(grp.member_keys) == 3

    def test_sparse_multidim_collapses_in_collapse_all_only(self):
        # [0][2],[1][2] — full-box 아님(부분채움)
        names = ["m[0][2]", "m[1][2]"]
        assert build(names).columns == names  # 기본: 미접기(full-box 아님)
        info = build(names, collapse_all=True)
        assert info.columns == ["m[2*3]"]  # 접힘

    def test_lone_element_not_collapsed(self):
        # 멤버 1개뿐이면 접지 않음(접을 의미 없음)
        info = build(["x[3]", "y"], collapse_all=True)
        assert info.columns == ["x[3]", "y"]

    def test_scalars_never_collapse(self):
        info = build(["a", "b", "c"], collapse_all=True)
        assert info.columns == ["a", "b", "c"]

    def test_single_dim_format_values_compact(self):
        names = ["v[0]", "v[1]", "v[2]"]
        grp = build(names, collapse_all=True).get_group("v[3]")
        vals = {"v[0]": "0x1A", "v[1]": "0x2B", "v[2]": "0x00"}
        # 단일차원은 콤마 구분 compact (줄바꿈 없이)
        assert grp.format_values(lambda k: vals.get(k)) == "[0]: 0x1A, [1]: 0x2B, [2]: 0x00"

    def test_single_dim_uniform_single_value(self):
        names = ["z[0]", "z[1]", "z[2]"]
        grp = build(names, collapse_all=True).get_group("z[3]")
        assert grp.format_values(lambda k: "0") == "0"

    def test_single_dim_format_actual(self):
        names = ["r[0]", "r[1]", "r[2]", "r[3]"]
        grp = build(names, collapse_all=True).get_group("r[4]")
        fails = {"r[2]"}
        text, ok = grp.format_actual(lambda k: k not in fails)
        assert not ok and text.startswith("NG (1/4)") and "[2]" in text


class TestRealWorldLargeArray:
    def test_buffer_5_7_7_collapses_to_one_column(self):
        """C# 원본 예시: buffer[5][7][7]=245요소 → 단일 컬럼(16384열/10열절단 회피)."""
        names = [f"buffer[{i}][{j}][{k}]"
                 for i in range(5) for j in range(7) for k in range(7)]
        assert len(names) == 245
        info = build(names)
        assert info.columns == ["buffer[5*7*7]"]
        grp = info.get_group("buffer[5*7*7]")
        assert grp.full_size() == 245
        # 절단 없이 1열 → 245개 요소가 한 셀로 정돈
        text, _ = grp.format_actual(lambda k: True)
        assert text == "OK"
