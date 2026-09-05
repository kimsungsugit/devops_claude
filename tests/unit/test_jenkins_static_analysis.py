"""_load_static_analysis 다중모듈(APP/BOOT) 로더 + shape 매퍼 테스트.

2026-07-03: 정적분석 SCM 로더가 도구별 단일-파일(sorted[-1]) → 모듈별 전부 반환으로
변경됨. 실제 KJPDS02 폴더는 CodeSonar/CodeEye/QAC/PMD 각각 APP·BOOT 모듈을 가지며
과거 로더는 알파벳 마지막 1개(BOOT)만 남겨 APP를 누락했다. 또 QAC=html(HMR)·CPD=txt(PMD)
포맷을 인식하도록 swsa 파서를 재사용한다. 본 테스트는 그 회귀를 고정한다.
"""
from backend.routers.jenkins import (
    _load_static_analysis,
    _sa_module_label,
    _sa_module_of,
    _sa_pmd_to_cpd,
    _sa_st201_to_qac,
)
from backend.services.swsa_pmd_parser import parse_pmd_cpd

# PMD CPD 텍스트 리포트 실측 형식 (2 블록, 파일 3개)
SAMPLE_PMD = (
    "Found a 30 line (120 tokens) duplication in the following files:\n"
    "Starting at line 10 of C:\\proj\\a.c\n"
    "Starting at line 50 of C:\\proj\\b.c\n"
    "   dup code...\n"
    "Found a 12 line (40 tokens) duplication in the following files:\n"
    "Starting at line 5 of C:\\proj\\a.c\n"
    "Starting at line 99 of C:\\proj\\c.c\n"
)


# ── 모듈 라벨 유틸 ──────────────────────────────────────────────────────────
def test_module_of_returns_parent_folder():
    assert _sa_module_of("U:/x/PMD/APP_260323/r.txt") == "APP_260323"
    assert _sa_module_of("U:\\x\\CodeSonar\\BOOT_260402\\f.pdf") == "BOOT_260402"


def test_module_label_extracts_prefix():
    assert _sa_module_label("U:/x/CodeSonar/APP_260326/f.pdf") == "APP"
    assert _sa_module_label("U:/x/CodeSonar/BOOT_260402/f.pdf") == "BOOT"
    # QAC 버전 폴더 (APP_날짜_버전) 도 prefix만
    assert _sa_module_label("U:/x/QAC/APP_260527_v0.05.37/QAC_HMR.html") == "APP"


# ── shape 매퍼 ─────────────────────────────────────────────────────────────
def test_pmd_to_cpd_shape():
    d = _sa_pmd_to_cpd(parse_pmd_cpd(SAMPLE_PMD))
    assert d["ok"] is True
    assert d["duplication_blocks"] == 2
    assert d["total_dup_lines"] == 42  # 30 + 12
    assert d["files_involved"] == 3  # a.c, b.c, c.c (basename dedup)
    # top_blocks 는 라인 내림차순
    assert d["top_blocks"][0]["lines"] == 30
    assert "a.c" in d["top_blocks"][0]["files"]


def test_pmd_to_cpd_empty_is_not_ok():
    d = _sa_pmd_to_cpd(parse_pmd_cpd("no duplication here"))
    assert d["ok"] is False
    assert d["duplication_blocks"] == 0


def test_st201_to_qac_shape():
    from backend.services.qac_parser import MatrixItem
    from backend.services.swsa_st201_binner import St201Result

    st = St201Result(total_functions=4)
    st.function_values[MatrixItem.V_G.name] = [1, 5, 12, 20]
    d = _sa_st201_to_qac(st)
    assert d["ok"] is True
    assert d["summary"]["function_count"] == 4
    assert d["summary"]["vg_max"] == 20
    assert d["summary"]["vg_over_10"] == 2  # 12, 20
    assert d["summary"]["vg_mean"] == 9.5


def test_st201_to_qac_no_functions_not_ok():
    from backend.services.swsa_st201_binner import St201Result

    d = _sa_st201_to_qac(St201Result(total_functions=0))
    assert d["ok"] is False
    assert d["summary"]["function_count"] == 0


# ── 로더 통합: 다중모듈(APP/BOOT) ────────────────────────────────────────────
class _FakeResolver:
    """recursive list_dir + read_bytes만 제공하는 최소 resolver 스텁."""

    def __init__(self, files, blobs):
        self._files = files
        self._blobs = blobs

    def list_dir(self, path, pattern="*", recursive=False):
        norm = path.replace("\\", "/").rstrip("/")
        return [f for f in self._files if f.replace("\\", "/").startswith(norm)]

    def read_bytes(self, path):
        return self._blobs[path]


def test_load_cpd_returns_both_modules(monkeypatch):
    """PMD txt가 APP·BOOT 두 모듈에 있으면 둘 다 반환 (과거엔 sorted 마지막 1개만)."""
    base = "U:/proj/PV"
    fapp = base + "/PMD/APP_260323/x_PMD_Report.txt"
    fboot = base + "/PMD/BOOT_260406/y_PMD_Report.txt"
    blobs = {fapp: SAMPLE_PMD.encode("utf-8"), fboot: SAMPLE_PMD.encode("utf-8")}

    import backend.services.file_resolver as fr
    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver([fapp, fboot], blobs))

    out = _load_static_analysis([base])
    assert out["ok"] is True
    cpd = out["cpd"]
    assert cpd["ok"] is True
    labels = sorted(m["label"] for m in cpd["modules"])
    assert labels == ["APP", "BOOT"]  # 핵심 회귀: APP 누락 방지
    for m in cpd["modules"]:
        assert m["duplication_blocks"] == 2
        assert m["source"].endswith("_PMD_Report.txt")


def test_load_cpd_latest_per_module(monkeypatch):
    """같은 prefix(APP)의 여러 날짜 폴더면 최신 1개만 (중복 합산 차단) + warning 기록."""
    base = "U:/proj/PV"
    old = base + "/PMD/APP_260101/old_PMD_Report.txt"
    new = base + "/PMD/APP_260901/new_PMD_Report.txt"
    blobs = {old: SAMPLE_PMD.encode("utf-8"), new: SAMPLE_PMD.encode("utf-8")}

    import backend.services.file_resolver as fr
    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver([old, new], blobs))

    out = _load_static_analysis([base])
    cpd = out["cpd"]
    assert len(cpd["modules"]) == 1  # APP prefix 하나만
    assert cpd["modules"][0]["source"] == new  # 최신 날짜
    assert any("최신" in w for w in out.get("warnings", []))


def test_load_cpd_xml_fallback_via_union(monkeypatch):
    """txt PMD가 없고 xml CPD만 있으면 확장자 분기로 xml 파서가 동작(합집합 폴백)."""
    base = "U:/proj/PV"
    fxml = base + "/CPD/APP_260501/cpd_result.xml"
    cpd_xml = (
        b'<?xml version="1.0"?><pmd-cpd>'
        b'<duplication lines="15" tokens="60">'
        b'<file path="C:/p/a.c"/><file path="C:/p/b.c"/></duplication>'
        b"</pmd-cpd>"
    )
    import backend.services.file_resolver as fr
    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver([fxml], {fxml: cpd_xml}))

    out = _load_static_analysis([base])
    cpd = out["cpd"]
    assert cpd["ok"] is True
    assert len(cpd["modules"]) == 1
    assert cpd["modules"][0]["duplication_blocks"] == 1
    assert cpd["modules"][0]["total_dup_lines"] == 15


def test_empty_paths_graceful(monkeypatch):
    import backend.services.file_resolver as fr
    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver([], {}))
    out = _load_static_analysis([])
    assert out["ok"] is False
    assert "detail" in out
    # 4 도구 모두 빈 modules
    for k in ("codesonar", "codeeye", "qac", "cpd"):
        assert out[k]["ok"] is False
        assert out[k]["modules"] == []
